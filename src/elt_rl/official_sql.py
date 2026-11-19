"""Constrain model SQL before sending it to a run-scoped Snowflake session."""

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError
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
                    raise PipelineError("query uses a function outside the allowlist")
            if isinstance(node, exp.Table):
                if not isinstance(node.this, exp.Identifier) or node.db or node.catalog:
                    raise PipelineError("use unqualified raw table names")
        read_raw = False
        for scope in traverse_scope(query):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    if source.name.lower() not in raw_tables:
                        raise PipelineError("table is outside the approved raw streams")
                    read_raw = True
        if not read_raw:
            raise PipelineError("query must reference a raw stream")
        return query.sql(dialect="snowflake", comments=False)
    except (SqlglotError, RecursionError):
        raise PipelineError("could not parse the Snowflake SELECT") from None
