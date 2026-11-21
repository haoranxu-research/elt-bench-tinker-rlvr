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


def public_sql_review(sql: str, model_section: str) -> list[str]:
    """Review SQL for common counting and rate pitfalls using public descriptions."""
    fields = (line.partition(": ") for line in model_section.splitlines())
    rate_definitions = {
        name.lower(): description.lower() for name, _, description in fields
        if "percentage" in description.lower()
    }
    query, = parse(sql, read="snowflake")
    zero_defaults = []
    rounded = []
    for projection in query.selects:
        name = projection.output_name.lower()
        description = rate_definitions.get(name)
        if not description or not isinstance(projection, exp.Alias):
            continue
        expression = projection.this
        if isinstance(expression, exp.Round):
            if "round" not in description:
                rounded.append(name)
            expression = expression.this
        if "null" in description or "default" in description:
            continue
        if isinstance(expression, exp.Case):
            defaults = [expression.args.get("default")]
        elif isinstance(expression, exp.Coalesce):
            defaults = expression.expressions
        else:
            continue
        if any(isinstance(value, exp.Literal) and value.is_number and value.to_py() == 0 for value in defaults):
            zero_defaults.append(name)
    feedback = []
    if zero_defaults:
        feedback.append(f"Review the zero defaults for {', '.join(zero_defaults)}. The public requirements "
                        "do not specify zero for undefined rates. Check rows with a missing denominator.")
    if rounded:
        feedback.append(f"Review the rounding of {', '.join(rounded)}. The public requirements "
                        "do not request rounding for these percentages.")
    if "average total pages of all authors" in model_section.lower() and any(
        "pages" in column.name.lower() for average in query.find_all(exp.Avg)
        for column in average.find_all(exp.Column)
    ):
        feedback.append("The public page average covers all authors. Verify that its input includes authors "
                        "with no related book rows and that their page totals contribute zero to the average "
                        "and to the comparison.")
    if "average sale price" in model_section.lower():
        maximum_prices = {
            alias.alias.lower() for alias in query.find_all(exp.Alias) if isinstance(alias.this, exp.Max)
            and any("price" in column.name.lower() for column in alias.this.find_all(exp.Column))
        }
        if any(column.name.lower() in maximum_prices for average in query.find_all(exp.Avg)
               for column in average.find_all(exp.Column)):
            feedback.append("The average sale price uses a column computed with MAX(price). Check the average "
                            "at the sale-line grain and keep it separate from the most expensive book ranking.")
    for count in query.find_all(exp.Count):
        value = count.this
        if not isinstance(value, exp.Distinct) or len(value.expressions) != 1:
            continue
        case = value.expressions[0]
        if not isinstance(case, exp.Case):
            continue
        branches = [branch.args.get("true") for branch in case.args.get("ifs", [])]
        branches.append(case.args.get("default"))
        if all(branch is None or isinstance(branch, (exp.Literal, exp.Null, exp.Boolean)) for branch in branches):
            feedback.append("COUNT(DISTINCT CASE ...) with constant results counts distinct branch values, "
                            "so it cannot count qualifying rows. Check what is being counted.")
            break
    for select in query.find_all(exp.Select):
        source = select.args.get("from_")
        author = source.this if source is not None else None
        for join in select.args.get("joins", ()):
            table = join.this
            condition = join.args.get("on")
            if (isinstance(author, exp.Table) and author.name.lower() == "author"
                    and isinstance(table, exp.Table) and table.name.lower() == "book_author"
                    and join.side == "LEFT" and any(
                        isinstance(column, exp.Column) and column.name.lower() == "author_id"
                        and column.table.lower() == table.alias_or_name.lower()
                        for projection in select.expressions for column in projection.find_all(exp.Column)
                    )):
                feedback.append(f"The author identifier comes from the nullable side of the left join "
                                f"({table.alias_or_name}.author_id). Use the preserved author table's identifier "
                                "for author-level grouping so unmatched authors keep distinct IDs.")
            if not isinstance(table, exp.Table) or table.name.lower() != "order_line" or condition is None:
                continue
            order_alias = table.alias_or_name.lower()
            joins_on_book = any(column.table.lower() == order_alias and column.name.lower() == "book_id"
                                for column in condition.find_all(exp.Column))
            selects_book_attributes = any(
                column.name.lower() in {"num_pages", "publication_date"} and column.table.lower() != order_alias
                for projection in select.expressions for column in projection.find_all(exp.Column)
            )
            if joins_on_book and selects_book_attributes:
                feedback.append("This SELECT combines book attributes with order_line through order_line.book_id. "
                                "Several order lines can refer to one book, repeating its date and page count. "
                                "Check that book-level counts and page totals are computed before the sales join.")
                return feedback
    return feedback


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
            # SQLGlot represents these SQL operators and predicates as functions, too.
            if isinstance(node, exp.Func) and not isinstance(node, (exp.And, exp.Or, exp.Exists)):
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
            if (scope.is_subquery and scope.expression.args.get("limit")
                    and any(column.table for column in scope.external_columns)):
                raise PipelineError("Snowflake does not support LIMIT in a correlated subquery. "
                                    "Use a ranked CTE and join its first row instead.")
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
