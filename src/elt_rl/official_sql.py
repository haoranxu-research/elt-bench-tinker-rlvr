"""Constrain model SQL before sending it to a run-scoped Snowflake session."""

from sqlglot import exp, parse
from sqlglot.errors import ParseError, SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import traverse_scope

from .contracts import PipelineError

FUNCTIONS = set("""
ABS AVG CAST CASE CEIL COALESCE CONCAT CONCAT_WS COUNT COUNT_IF DATE DATE_ADD
DATE_DIFF DATE_PART DATE_TRUNC DAY EXTRACT FIRST_VALUE FLOOR IFF IF INITCAP
LAG LAST_VALUE LEAD LENGTH LEFT LOWER LTRIM MAX MIN MONTH NULLIF NVL
PERCENTILE_CONT RANK DENSE_RANK REPLACE RIGHT ROUND ROW_NUMBER RTRIM
SQRT STR_POSITION SUBSTRING SUM TIME_TO_STR TIMESTAMP_TRUNC TO_CHAR TO_DECIMAL
TO_DOUBLE TO_NUMBER TO_VARCHAR TRIM TRY_CAST TRY_TO_DATE UPPER YEAR
""".split())

FORBIDDEN_NODES = {
    "Command", "Dot", "Hint", "Into", "Lateral", "Parameter", "Placeholder",
    "SessionParameter", "Stage", "StageOptions", "TableFromRows", "TableSample",
    "Values", "WithTableHint",
}


def _sql_error(message: str, line: int | None = None, column: int | None = None) -> PipelineError:
    location = f"line {line}" if line else ""
    if line and column:
        location += f", column {column}"
    return PipelineError(f"{location}: {message}" if location else message)


def _identifier_label(name: str) -> str:
    return "".join(ch for ch in name[:80] if ch.isalnum() or ch in "_$") or "(quoted identifier)"


def safe_select(sql: str, raw_tables: frozenset[str]) -> str:
    try:
        statements = parse(sql, read="snowflake")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise PipelineError("provide exactly one Snowflake SELECT query")
        query = statements[0]
        if any(cte.args.get("recursive") for cte in query.find_all(exp.With)):
            raise PipelineError("recursive queries are unavailable")
        for node in query.walk():
            if type(node).__name__ in FORBIDDEN_NODES or isinstance(node, (exp.DDL, exp.DML)):
                raise PipelineError("query uses a disallowed SQL operation")
            if isinstance(node, exp.Func):
                name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
                if name not in FUNCTIONS:
                    raise _sql_error(f"function {_identifier_label(name)} is outside the allowlist",
                                     node.meta.get("line"))
            if isinstance(node, exp.Table):
                if not isinstance(node.this, exp.Identifier):
                    raise PipelineError("use unqualified raw table names")
                if node.db or node.catalog:
                    raise _sql_error("use unqualified raw table names", node.this.meta.get("line"),
                                     node.this.meta.get("col"))
        read_raw = False
        # Fold unquoted aliases for Snowflake scope checks while preserving the generated SQL.
        scoped_query = normalize_identifiers(query.copy(), dialect="snowflake")
        for scope in traverse_scope(scoped_query):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    if source.name.lower() not in raw_tables:
                        identifier = source.this
                        raise _sql_error(
                            f"relation {_identifier_label(source.name)} is neither an approved raw table nor a CTE in scope",
                            identifier.meta.get("line"), identifier.meta.get("col"),
                        )
                    read_raw = True
        if not read_raw:
            raise PipelineError("query must reference a raw stream")
        return query.sql(dialect="snowflake", comments=False)
    except ParseError as error:
        issue = next(iter(error.errors), {})
        description = issue.get("description", "invalid SQL syntax")
        if "'to' missing" in description and "Cast" in description:
            description = "CAST requires an expression followed by AS and a target type"
        description = " ".join(description.replace("<", "(").replace(">", ")").split())[:160]
        raise _sql_error(description, issue.get("line"), issue.get("col")) from None
    except (SqlglotError, RecursionError):
        raise PipelineError("could not validate the Snowflake SELECT") from None
