import inspect
from pathlib import Path
from typing import Optional, Any, Dict, Union, List, Tuple, Callable, Iterable
import json
import os

import asyncpg
from psycopg2.sql import SQL

from utils.loggers.error_logger import ErrorLogger
from utils.result import Result
from functools import wraps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_STRUCTURE_ROOT = f"{PROJECT_ROOT}/db/db_files"


def PostgreSQL_wrapper(func: Optional[Callable] = None,
                       access_level: int = 0,
                       require_connection: bool = False,
                       max_retries: int = 3):
    if func is None:
        def decorator(f):
            return PostgreSQL_wrapper(func=f, access_level=access_level,
                                      require_connection=require_connection,
                                      max_retries=max_retries)

        return decorator

    @wraps(func)
    async def async_wrapper(self, *args, **kwargs):
        _before_method()
        if access_level > self._db_owner.access_level:
            result = Result(success=False, operation=func.__name__,
                            error_message=f"Access denied: required level {access_level}, but current level is {self._db_owner.access_level}.")
            _after_method(result)
            return result

        result = Result(success=False, operation=func.__name__)

        # Abort early if any arg is a failed Result
        for name, val in list(enumerate(args)) + list(kwargs.items()):
            if isinstance(val, Result) and not val.success:
                result.error_message = f"Aborted: input argument '{name}' for {func.__name__} received failed result:\n {val.error_message}"
                result.data = val.data
                _after_method(result)
                return result

        # Unwrap Result objects
        args = tuple(arg.data if isinstance(arg, Result) else arg for arg in args)
        kwargs = {k: v.data if isinstance(v, Result) else v for k, v in kwargs.items()}

        attempts = 0
        while attempts < max_retries:
            try:
                if require_connection:
                    # Await if connect is async
                    if inspect.iscoroutinefunction(self._db_owner.connect):
                        connected = await self._db_owner.connect()
                    else:
                        connected = self._db_owner.connect()
                    if not connected:
                        raise Exception("Database connection failed in PostgreSQL level.")

                # Await if func is async
                if inspect.iscoroutinefunction(func):
                    data = await func(self, *args, **kwargs)
                else:
                    data = func(self, *args, **kwargs)

                if isinstance(data, Result):
                    _after_method(data)
                    return data  # Already a Result, just return it

                result.success = True
                result.data = data
                break

            except Exception as e:
                attempts += 1
                # Await reset if async
                if isinstance(e, asyncpg.TooManyConnectionsError):
                    ErrorLogger.background_log_error(6, f"Too many connections, skipping reset.", e)
                    break  # Do not retry/reset here!
                else:
                    if inspect.iscoroutinefunction(self._db_owner.reset):
                        await self._db_owner.reset()
                    else:
                        self._db_owner.reset()
                if attempts == max_retries:
                    result.error_message = f"{type(e).__name__} Exceeded max retries ({func.__name__}): {str(e)}"
                    ErrorLogger.background_log_error(6,
                                                     f"{type(e).__name__} Exceeded max retries ({func.__name__}): {str(e)}",
                                                     e)
                    break

        _after_method(result)
        return result

    # If original func is coroutine function, return async wrapper
    if inspect.iscoroutinefunction(func):
        return async_wrapper
    else:
        # Provide sync wrapper fallback if you want sync support
        @wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            _before_method()
            if access_level > self._db_owner.access_level:
                result = Result(success=False, operation=func.__name__,
                                error_message=f"Access denied: required level {access_level}, but current level is {self._db_owner.access_level}.")
                _after_method(result)
                return result

            result = Result(success=False, operation=func.__name__)
            # (Similar logic here, but skipping for brevity)
            try:
                if require_connection and not self._db_owner.connect():
                    raise Exception("Database connection failed in PostgreSQL level.")
                data = func(self, *args, **kwargs)
                if isinstance(data, Result):
                    _after_method(data)
                    return data
                result.success = True
                result.data = data
            except Exception as e:
                result.error_message = f"{type(e).__name__}: {str(e)}"
                ErrorLogger.background_log_error(6, result.error_message, e)
            _after_method(result)
            return result

        return sync_wrapper


def _before_method():
    pass


def _after_method(result=None):
    pass


class PostgreSQL:
    def __init__(self, db_owner) -> None:
        self._db_owner = db_owner

    @property
    def pool(self):
        return getattr(self._db_owner, "_pool", None)

    @pool.setter
    def pool(self, value):
        setattr(self._db_owner, "_pool", value)

    @property
    def access_level(self):
        return getattr(self._db_owner, "_access_level", 0)

    @access_level.setter
    def access_level(self, value):
        setattr(self._db_owner, "_access_level", value)

    @property
    def structure_root(self):
        return getattr(self._db_owner, "_structure_root", None)

    @structure_root.setter
    def structure_root(self, value):
        setattr(self._db_owner, "_structure_root", value)

    @PostgreSQL_wrapper(access_level=6, require_connection=True)
    async def list_tables(self) -> list:
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(query)
        tables = [row['table_name'] for row in rows]
        return tables

    @PostgreSQL_wrapper(access_level=6, require_connection=True)
    async def get_database_structure(self) -> dict:
        tables = await self.list_tables()
        if isinstance(tables, Result):
            tables = tables.data

        db_structure = {}

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for table in tables:
                    query = """
                        SELECT c.column_name,
                               c.data_type,
                               CASE
                                   WHEN c.character_maximum_length IS NOT NULL
                                       THEN c.data_type || '(' || c.character_maximum_length || ')'
                                   ELSE c.data_type
                               END AS full_data_type,
                               c.is_nullable,
                               c.column_default,
                               EXISTS (
                                   SELECT 1
                                   FROM information_schema.table_constraints tc
                                   JOIN information_schema.constraint_column_usage ccu
                                        ON ccu.constraint_name = tc.constraint_name
                                   WHERE tc.table_name = c.table_name
                                     AND ccu.column_name = c.column_name
                                     AND tc.constraint_type = 'PRIMARY KEY'
                               ) AS is_primary_key,
                               EXISTS (
                                   SELECT 1
                                   FROM information_schema.table_constraints tc
                                   JOIN information_schema.constraint_column_usage ccu
                                        ON ccu.constraint_name = tc.constraint_name
                                   WHERE tc.table_name = c.table_name
                                     AND ccu.column_name = c.column_name
                                     AND tc.constraint_type = 'UNIQUE'
                               ) AS is_unique
                        FROM information_schema.columns c
                        WHERE c.table_name = $1
                        ORDER BY c.ordinal_position
                    """

                    rows = await conn.fetch(query, table)

                    db_structure[table] = [
                        {
                            "column_name": row["column_name"],
                            "data_type": row["full_data_type"],
                            "is_nullable": row["is_nullable"],
                            "default": row["column_default"],
                            "is_primary_key": row["is_primary_key"],
                            "is_unique": row["is_unique"]
                        }
                        for row in rows
                    ]

        json_path = os.path.join(DB_STRUCTURE_ROOT, self.structure_root)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(db_structure, f, indent=4)

        return db_structure

    @PostgreSQL_wrapper(access_level=9, require_connection=True)
    async def create_table(self, table_name: str, columns: Dict[str, str]) -> str:
        col_defs = ", ".join(
            f"{quote_ident(col)} {dtype}" for col, dtype in columns.items()
        )
        query = f'CREATE TABLE IF NOT EXISTS {quote_ident(table_name)} ({col_defs})'

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)

        await self.get_database_structure()
        return f"table {table_name} successfully created."

    @PostgreSQL_wrapper(access_level=10, require_connection=True)
    async def delete_table(self, table_name: str) -> str:
        query = f'DROP TABLE IF EXISTS {quote_ident(table_name)}'

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)

        await self.get_database_structure()
        return f"table {table_name} successfully deleted."

    @PostgreSQL_wrapper(access_level=7, require_connection=True)
    async def add_column(
            self,
            table_name: str,
            column_name: str,
            column_type: str,
            unique: bool = False,
            nullable: bool = True,
            default: Optional[str] = None,
            check: Optional[str] = None
    ) -> str:
        col_parts = [column_type]

        if not nullable:
            col_parts.append("NOT NULL")
        else:
            col_parts.append("NULL")

        if unique:
            col_parts.append("UNIQUE")

        if default is not None:
            col_parts.append(f"DEFAULT {default}")

        if check is not None:
            col_parts.append(f"CHECK({check})")

        col_def = " ".join(col_parts)
        query = f'''
            ALTER TABLE {quote_ident(table_name)}
            ADD COLUMN IF NOT EXISTS {quote_ident(column_name)} {col_def}
        '''

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)

        await self.get_database_structure()
        return f"Column '{column_name}' successfully added to table '{table_name}'."

    @PostgreSQL_wrapper(access_level=8, require_connection=True)
    async def remove_column(self, table_name: str, column_name: str) -> str:
        query = f'ALTER TABLE {quote_ident(table_name)} DROP COLUMN IF EXISTS {quote_ident(column_name)}'

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)

        await self.get_database_structure()  # Update JSON
        return f"Column '{column_name}' successfully removed from table '{table_name}'."

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def add_row(
            self,
            table_name: str,
            row_data: Dict[str, Any],
            conflict_columns: Optional[List[str]] = None
    ) -> Result:
        columns = list(row_data.keys())

        from psycopg2._json import Json

        def convert_value(val):
            if isinstance(val, Json):
                return val.adapted
            return val

        values = [convert_value(v) for v in row_data.values()]
        quoted_columns = ", ".join(quote_ident(col) for col in columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if not conflict_columns:
                    query = f"""
                        INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                        VALUES ({placeholders})
                    """
                    await conn.execute(query, *values)
                    return Result(True, f"Row successfully inserted into table '{table_name}'.", "", None)

                quoted_conflict = ", ".join(quote_ident(col) for col in conflict_columns)
                update_columns = [col for col in columns if col not in conflict_columns]

                if not update_columns:
                    query = f"""
                        INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                        VALUES ({placeholders})
                        ON CONFLICT ({quoted_conflict}) DO NOTHING
                    """
                    await conn.execute(query, *values)
                    return Result(True,
                                  f"Row successfully inserted into table '{table_name}' with ON CONFLICT DO NOTHING.",
                                  "", None)

                set_clause = ", ".join(
                    f"{quote_ident(col)} = EXCLUDED.{quote_ident(col)}" for col in update_columns
                )

                query = f"""
                    INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                    VALUES ({placeholders})
                    ON CONFLICT ({quoted_conflict}) DO UPDATE SET {set_clause}
                """
                await conn.execute(query, *values)
                return Result(True,
                              f"Row successfully inserted/updated in table '{table_name}' with ON CONFLICT DO UPDATE.",
                              "", None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def add_row_returning_id(
            self,
            table_name: str,
            row_data: Dict[str, Any],
            conflict_columns: Optional[List[str]] = None
    ) -> Result:

        columns = list(row_data.keys())
        values = list(row_data.values())

        quoted_columns = ", ".join(quote_ident(col) for col in columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))

        async with self.pool.acquire() as conn:
            async with conn.transaction():

                if not conflict_columns:
                    query = f"""
                        INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                        VALUES ({placeholders})
                        RETURNING id;
                    """
                    row = await conn.fetchrow(query, *values)
                    return Result(True, f"Row inserted into '{table_name}'.", "", row["id"] if row else None)

                quoted_conflict = ", ".join(quote_ident(col) for col in conflict_columns)
                update_columns = [col for col in columns if col not in conflict_columns]

                if not update_columns:
                    query = f"""
                        INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                        VALUES ({placeholders})
                        ON CONFLICT ({quoted_conflict}) DO NOTHING
                        RETURNING id;
                    """
                    row = await conn.fetchrow(query, *values)
                    return Result(True, f"Row inserted into '{table_name}' with ON CONFLICT DO NOTHING.", "",
                                  row["id"] if row else None)

                set_clause = ", ".join(
                    f"{quote_ident(col)} = EXCLUDED.{quote_ident(col)}" for col in update_columns
                )

                query = f"""
                    INSERT INTO {quote_ident(table_name)} ({quoted_columns})
                    VALUES ({placeholders})
                    ON CONFLICT ({quoted_conflict}) DO UPDATE SET {set_clause}
                    RETURNING id;
                """
                row = await conn.fetchrow(query, *values)
                return Result(True, f"Row inserted/updated in '{table_name}' with ON CONFLICT DO UPDATE.", "",
                              row["id"] if row else None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def insert_and_return_id(self,
                                   table: str,
                                   row_data: dict,
                                   id_column: str = "id"):

        cols = ', '.join(quote_ident(col) for col in row_data.keys())
        placeholders = ', '.join(f'${i + 1}' for i in range(len(row_data)))
        query = f"""
            INSERT INTO {quote_ident(table)} ({cols})
            VALUES ({placeholders})
            RETURNING {quote_ident(id_column)};
        """
        values = list(row_data.values())

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.fetchrow(query, *values)

        return result[id_column] if result else None

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def delete_row(
            self,
            table_name: str,
            conditions: Dict[str, Any]
    ) -> Result:
        where_clauses = [f"{quote_ident(k)} = ${i + 1}" for i, k in enumerate(conditions.keys())]
        query = f"DELETE FROM {quote_ident(table_name)} WHERE {' AND '.join(where_clauses)}"

        async with self.pool.acquire() as conn:
            await conn.execute(query, *conditions.values())

        return Result(True, "delete_row", "", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def update_row(
            self,
            table_name: str,
            new_values: Dict[str, Any],
            conditions: Dict[str, Any],
            updated_at_column: Optional[str] = None
    ) -> Result:
        set_clauses = []
        where_clauses = []
        params = []
        param_index = 1

        class RawSQL:
            def __init__(self, expression: str):
                self.expression = expression

        if new_values is not None:
            for k, v in new_values.items():
                if isinstance(v, RawSQL):
                    set_clauses.append(f"{quote_ident(k)} = {v.expression}")
                else:
                    set_clauses.append(f"{quote_ident(k)} = ${param_index}")
                    params.append(v)
                    param_index += 1

        # Build WHERE clause
        for k, v in conditions.items():
            where_clauses.append(f"{quote_ident(k)} = ${param_index}")
            params.append(v)
            param_index += 1

        query = f"""
            UPDATE {quote_ident(table_name)}
            SET {', '.join(set_clauses)}
            WHERE {' AND '.join(where_clauses)}
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                result = await conn.execute(query, *params)

        # Example result string: "UPDATE 1"
        rowcount = int(result.split()[-1]) if result.startswith("UPDATE") else 0

        if rowcount == 0:
            return Result(False, "update_row",
                          f"No rows updated in table '{table_name}' with conditions: {conditions}.", None)

        return Result(True, "update_row",
                      f"Row(s) successfully updated in table '{table_name}' with new values: {new_values} and conditions: {conditions}.",
                      None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_row(self, table_name: str, conditions: Dict[str, Any]) -> Any:
        where_clauses = [f"{quote_ident(k)} = ${i + 1}" for i, k in enumerate(conditions.keys())]
        query = f"SELECT * FROM {quote_ident(table_name)} WHERE {' AND '.join(where_clauses)}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *conditions.values())

        if row:
            return Result(True, "get_row", "", dict(row))
        return Result(False, "get_row", f"row was not found with conditions: {conditions} in table: {table_name}", None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_rows_where(
            self,
            table_name: str,
            conditions: List[Tuple[str, str, Any]]
    ) -> Any:
        where_clauses = []
        params = []
        param_index = 1

        for col, op, val in conditions:
            if op not in ("=", "!=", "<>", "<", ">", "<=", ">=", "LIKE", "ILIKE", "IN", "NOT IN"):
                raise ValueError(f"Unsupported operator: {op}")

            if op in ("IN", "NOT IN") and isinstance(val, (list, tuple)):
                placeholders = ', '.join(f"${param_index + i}" for i in range(len(val)))
                clause = f"{quote_ident(col)} {op} ({placeholders})"
                where_clauses.append(clause)
                params.extend(val)
                param_index += len(val)
            else:
                clause = f"{quote_ident(col)} {op} ${param_index}"
                where_clauses.append(clause)
                params.append(val)
                param_index += 1

        query = f"SELECT * FROM {quote_ident(table_name)} WHERE {' AND '.join(where_clauses)}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(query, *params)

        data = [dict(row) for row in rows]
        return data if data else None

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def update_rows_where(
            self,
            table_name: str,
            new_values: Dict[str, Any],
            conditions: List[Tuple[str, str, Any]]
    ) -> bool:
        param_index = 1
        params = []

        set_clauses = []
        for key, value in new_values.items():
            set_clauses.append(f"{quote_ident(key)} = ${param_index}")
            params.append(value)
            param_index += 1

        where_clauses = []
        for col, op, val in conditions:
            if op not in ("=", "!=", "<>", "<", ">", "<=", ">=", "LIKE", "ILIKE", "IN", "NOT IN"):
                raise ValueError(f"Unsupported operator: {op}")

            if op in ("IN", "NOT IN") and isinstance(val, (list, tuple)):
                placeholders = ', '.join(f"${param_index + i}" for i in range(len(val)))
                clause = f"{quote_ident(col)} {op} ({placeholders})"
                params.extend(val)
                param_index += len(val)
            else:
                clause = f"{quote_ident(col)} {op} ${param_index}"
                params.append(val)
                param_index += 1
            where_clauses.append(clause)

        query = f"UPDATE {quote_ident(table_name)} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query, *params)
        return True

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_value(
            self,
            table_name: str,
            conditions: Dict[str, Any],
            column: str
    ) -> Any | None:
        where_clauses = [f"{quote_ident(k)} = ${i + 1}" for i, k in enumerate(conditions.keys())]
        query = f"SELECT {quote_ident(column)} FROM {quote_ident(table_name)} WHERE {' AND '.join(where_clauses)}"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *conditions.values())
            if row:
                return row[column]
        return None

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_all_values(
            self,
            table_name: str,
            conditions: Dict[str, Any],
            column: str
    ) -> Result:
        """
        Returns a list of values from the specified column for all rows
        matching the provided conditions.
        """

        where_clauses = [f"{quote_ident(k)} = ${i + 1}" for i, k in enumerate(conditions.keys())]
        query = f"""
            SELECT {quote_ident(column)}
            FROM {quote_ident(table_name)}
            WHERE {' AND '.join(where_clauses)}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *conditions.values())

        return Result(True, "get_all_values", "", [row[column] for row in rows if column in row])

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_jsonb_nested_value(
            self,
            table_name: str,
            key_value: Union[int, str],
            jsonb_column: str,
            keys: tuple[str, ...],
            key_column: str = "user_id"
    ) -> Result:
        if not keys:
            raise ValueError("At least one key is required.")

        # Build JSONB access chain using -> operator for full JSON type access
        access_chain = " -> ".join(f"${i + 1}" for i in range(len(keys)))
        jsonb_access = f"{quote_ident(jsonb_column)} -> {access_chain}"

        # WHERE clause parameter index
        param_offset = len(keys) + 1
        query = f"""
            SELECT {jsonb_access} AS value
            FROM {quote_ident(table_name)}
            WHERE {quote_ident(key_column)} = ${param_offset}
        """

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(query, *(str(k) for k in keys), key_value)

            if row and row["value"] is not None:
                # Parse JSON string to native Python object (int, str, dict, list, etc.)
                return Result(True, "get_jsonb_nested_value", "", row["value"])
            else:
                return Result(False, "get_jsonb_nested_value", "", None)
        except Exception as e:
            return Result(False, "get_jsonb_nested_value", str(e), None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_jsonb_nested_value_composite_key(
            self,
            table_name: str,
            user_id: int,
            chat_id: int,
            jsonb_column: str,
            keys: tuple[str, ...]
    ) -> Result:
        if not keys:
            raise ValueError("At least one key is required.")

        # Use -> for all JSON path accesses to preserve JSON types
        access_chain = " -> ".join(f"${i + 1}" for i in range(len(keys)))
        jsonb_access = f"{quote_ident(jsonb_column)} -> {access_chain}"

        param_offset = len(keys) + 1
        query = f"""
            SELECT {jsonb_access} AS value
            FROM {quote_ident(table_name)}
            WHERE chat_id = ${param_offset} AND user_id = ${param_offset + 1}
        """

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(query, *(str(k) for k in keys), chat_id, user_id)

            if row and row["value"] is not None:
                return Result(True, "get_jsonb_nested_value_composite_key", "", row["value"])
            else:
                return Result(False, "get_jsonb_nested_value_composite_key", "", None)

        except Exception as e:
            return Result(False, "get_jsonb_nested_value_composite_key", str(e), None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def update_jsonb_nested_value(
            self,
            table_name: str,
            user_id: int,
            jsonb_column: str,
            keys: tuple[str, ...],
            new_value: Any,
            updated_at_column: str = "updated_at"
    ) -> bool:
        if not keys:
            raise ValueError("At least one nested key is required for JSONB update.")

        jsonb_path = "{" + ",".join(keys) + "}"
        key_path_pg_array = list(keys)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Step 1: Check if the path exists
                check_query = f"""
                    SELECT {quote_ident(jsonb_column)} #> $1 AS current_value
                    FROM {quote_ident(table_name)}
                    WHERE user_id = $2
                """
                result = await conn.fetchrow(check_query, key_path_pg_array, user_id)
                if not result:
                    raise ValueError(f"No row found with user_id={user_id}")

                # Step 2: Perform update
                update_query = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(jsonb_column)} = jsonb_set({quote_ident(jsonb_column)}, $1, $2::jsonb, true),
                        {quote_ident(updated_at_column)} = NOW()
                    WHERE user_id = $3
                """
                await conn.execute(update_query, jsonb_path, json.dumps(new_value), user_id)

        return True

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_row_by_composite_keys(
            self,
            table_name: str,
            constraints: dict[str, Any]
    ) -> Result:
        if not constraints:
            raise ValueError("At least one constraint key is required.")

        keys = list(constraints.keys())
        values = list(constraints.values())

        # Build WHERE clause with dynamic keys
        where_clause = " AND ".join(f"{quote_ident(k)} = ${i + 1}" for i, k in enumerate(keys))

        query = f"""
            SELECT *
            FROM {quote_ident(table_name)}
            WHERE {where_clause}
        """

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(query, *values)

            if row:
                return Result(True, "get_row_by_composite_keys", "", dict(row))
            else:
                return Result(False, "get_row_by_composite_keys", "No matching row found.", None)
        except Exception as e:
            return Result(False, "get_row_by_composite_keys", str(e), None)

    async def update_jsonb_nested(
            self,
            table_name: str,
            key_value: Union[int, str],
            json_column: str,
            *keys: Optional[str],
            new_value: Any,
            updated_at: bool = True,
            updated_at_column: str = "updated_at",
            key_column: str = "user_id"
    ) -> Result:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if not keys:
                    query = f"""
                        UPDATE {quote_ident(table_name)}
                        SET {quote_ident(json_column)} = $1::jsonb
                        WHERE {quote_ident(key_column)} = $2
                    """
                    await conn.execute(query, new_value, key_value)
                else:
                    key_path_pg_array = list(keys)
                    check_query = f"""
                        SELECT {quote_ident(json_column)} #> $1 AS current_value
                        FROM {quote_ident(table_name)}
                        WHERE {quote_ident(key_column)} = $2
                    """
                    result = await conn.fetchrow(check_query, key_path_pg_array, key_value)
                    if not result:
                        return Result(False, "update_jsonb_nested", f"No row found with {key_column}={key_value}", None)

                    update_query = f"""
                        UPDATE {quote_ident(table_name)}
                        SET {quote_ident(json_column)} = jsonb_set({quote_ident(json_column)}, $1, $2::jsonb, true)
                        WHERE {quote_ident(key_column)} = $3
                    """
                    await conn.execute(update_query, key_path_pg_array, new_value, key_value)

        return Result(True, "update_jsonb_nested", "", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def update_jsonb_nested_composite_key(
            self,
            table_name: str,
            user_id: int,
            chat_id: int,
            json_column: str,
            *keys: str,
            new_value: Any,
            updated_at_column: str = "updated_at"
    ) -> Result:
        if not keys:
            raise ValueError("At least one nested key is required for JSONB update.")

        jsonb_path = "{" + ",".join(keys) + "}"
        key_path_pg_array = list(keys)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Step 1 — Check if path exists
                check_query = f"""
                    SELECT {quote_ident(json_column)} #> $1 AS current_value
                    FROM {quote_ident(table_name)}
                    WHERE chat_id = $2 AND user_id = $3
                """
                result = await conn.fetchrow(check_query, key_path_pg_array, chat_id, user_id)
                if not result:
                    return Result(False, "update_jsonb_nested_composite_key",
                                  f"No row found with chat_id={chat_id} and user_id={user_id}", None)

                # Step 3 — Update JSONB field + updated_at column
                update_query = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(json_column)} = jsonb_set({quote_ident(json_column)}, $1, $2::jsonb, true)
                    WHERE chat_id = $3 AND user_id = $4
                """
                await conn.execute(update_query, key_path_pg_array, new_value, chat_id, user_id)

        return Result(True, "update_jsonb_nested_composite_key", "", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def update_jsonb_nested_multi_key(
            self,
            table_name: str,
            json_column: str,
            composite_keys: dict[str, Any],
            *keys: str,
            new_value: Any,
    ) -> Result:
        if not keys:
            return Result(False, "update_jsonb_nested_multi_key", "At least one nested key is required", None)

        if not composite_keys:
            return Result(False, "update_jsonb_nested_multi_key", "At least one composite key is required", None)

        key_path_pg_array = list(keys)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Build WHERE clause starting at $3
                where_clauses = []
                params_check = [key_path_pg_array]  # $1 = JSON path
                i = 2  # start numbering for composite keys
                for col, val in composite_keys.items():
                    where_clauses.append(f"{quote_ident(col)} = ${i}")
                    params_check.append(val)
                    i += 1
                where_sql = " AND ".join(where_clauses)
                # Check if row exists
                check_query = f"""
                    SELECT {quote_ident(json_column)} #> $1 AS current_value
                    FROM {quote_ident(table_name)}
                    WHERE {where_sql}
                """
                result = await conn.fetchrow(check_query, *params_check)
                if not result:
                    return Result(False, "update_jsonb_nested_multi_key",
                                  f"No row found with {composite_keys}", None)

                where_clauses = []
                params_check = [key_path_pg_array]  # $1 = JSON path
                i = 3  # start numbering for composite keys
                for col, val in composite_keys.items():
                    where_clauses.append(f"{quote_ident(col)} = ${i}")
                    params_check.append(val)
                    i += 1
                where_sql = " AND ".join(where_clauses)

                update_query = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(json_column)} = jsonb_set({quote_ident(json_column)}, $1, $2::jsonb, true)
                    WHERE {where_sql}
                """
                await conn.execute(update_query, key_path_pg_array, new_value, *composite_keys.values())
        return Result(True, "update_jsonb_nested_multi_key", "", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def get_jsonb_nested_multi_key(
            self,
            table_name: str,
            json_column: str,
            composite_keys: dict[str, Any],
            *keys: str,
    ) -> Result:
        """
        Retrieve a nested JSONB value at the given path from a PostgreSQL table.
        Handles missing rows or missing JSON paths gracefully.

        :param table_name: Name of the table
        :param json_column: JSONB column to query
        :param composite_keys: Dictionary of column=value pairs for the WHERE clause
        :param keys: Nested JSON keys to traverse
        :return: Result object with the retrieved value or error message
        """
        if not keys:
            return Result(False, "get_jsonb_nested_multi_key", "At least one nested key is required", None)

        if not composite_keys:
            return Result(False, "get_jsonb_nested_multi_key", "At least one composite key is required", None)

        key_path_pg_array = list(keys)

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Build WHERE clause starting at $2
                    where_clauses = []
                    params = [key_path_pg_array]  # $1 = JSON path
                    i = 2
                    for col, val in composite_keys.items():
                        where_clauses.append(f"{quote_ident(col)} = ${i}")
                        params.append(val)
                        i += 1
                    where_sql = " AND ".join(where_clauses)

                    query = f"""
                        SELECT {quote_ident(json_column)} #> $1 AS value
                        FROM {quote_ident(table_name)}
                        WHERE {where_sql}
                    """
                    row = await conn.fetchrow(query, *params)

                    if not row:
                        return Result(False, "get_jsonb_nested_multi_key",
                                      f"No row found matching conditions: {composite_keys}", None)

                    value = row["value"]

                    if value is None:
                        return Result(False, "get_jsonb_nested_multi_key",
                                      f"JSON path {keys} does not exist in column {json_column}", None)

                    return Result(True, "get_jsonb_nested_multi_key", "", value)
        except Exception as e:
            # Catch any unexpected database errors gracefully
            return Result(False, "get_jsonb_nested_multi_key",
                          f"Unexpected error: {str(e)}", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def append_jsonb_array(
            self,
            table_name: str,
            user_id: int,
            jsonb_column: str,
            append_value: Any,
            updated_at_column: str = "updated_at"
    ) -> Result:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Step 1: Check if row exists
                check_query = f"""
                    SELECT {quote_ident(jsonb_column)}
                    FROM {quote_ident(table_name)}
                    WHERE chat_id = $1
                """
                result = await conn.fetchrow(check_query, user_id)
                if not result:
                    return Result(False, "append_jsonb_array", f"No row found with chat_id={user_id}", None)

                # Step 2: Append to JSONB array using jsonb_set and concatenation
                update_query = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(jsonb_column)} = 
                            COALESCE({quote_ident(jsonb_column)}, '[]'::jsonb) || $1::jsonb
                    WHERE chat_id = $2
                """
                await conn.execute(update_query, json.dumps([append_value]), user_id)

        return Result(True, "append_jsonb_array", "", None)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def append_jsonb_array_composite_key(
            self,
            table_name: str,
            user_id: int,
            chat_id: int,
            jsonb_column: str,
            append_value: Any,
            updated_at_column: str = "updated_at"
    ) -> Result:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Step 1 — Check if row exists
                check_query = f"""
                    SELECT {quote_ident(jsonb_column)}
                    FROM {quote_ident(table_name)}
                    WHERE chat_id = $1 AND user_id = $2
                """
                row = await conn.fetchrow(check_query, chat_id, user_id)
                if not row:
                    return Result(False, "append_jsonb_array_composite_key",
                                  f"No row found with chat_id={chat_id} and user_id={user_id}", None)

                # Step 2 — Append to JSONB array + update timestamp
                update_query = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(jsonb_column)} = 
                            COALESCE({quote_ident(jsonb_column)}, '[]'::jsonb) || $1::jsonb
                    WHERE chat_id = $2 AND user_id = $3
                """
                await conn.execute(update_query, [append_value], chat_id, user_id)

        return Result(True, "append_jsonb_array_composite_key", "", None)

    @PostgreSQL_wrapper(access_level=8, require_connection=True)
    async def get_all_rows(self, table_name: str) -> Result:
        query = f"SELECT * FROM {quote_ident(table_name)}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(query)

        return Result(True, "get_all_rows", "", [dict(r) for r in rows]) if rows else Result(False, "get_all_rows",
                                                                                             "No rows were found.",
                                                                                             None)

    @PostgreSQL_wrapper(access_level=10, require_connection=True)
    async def execute_raw_query(
            self,
            query: str,
            params: Optional[Union[List[Any], Tuple]] = None
    ) -> Result:
        operation = "executing raw query"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if query.strip().lower().startswith("select"):
                    data = await conn.fetch(query, *(params or []))
                    return Result(success=True, data=data, operation=operation)
                else:
                    await conn.execute(query, *(params or []))
                    return Result(success=True, operation=operation)

    @PostgreSQL_wrapper(access_level=10, require_connection=True)
    async def clear_table(self, table_name: str) -> bool:
        query = f"TRUNCATE TABLE {quote_ident(table_name)}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)
        return True

    @PostgreSQL_wrapper(access_level=2, require_connection=True)
    async def get_column_names(self, table_name: str) -> list[str] | None:
        query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                columns = await conn.fetch(query, table_name)
        return [row['column_name'] for row in columns] if columns else None

    @PostgreSQL_wrapper(access_level=9, require_connection=True)
    async def rename_table(self, old_name: str, new_name: str) -> bool:
        query = f'ALTER TABLE {quote_ident(old_name)} RENAME TO {quote_ident(new_name)}'
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query)
        await self.get_database_structure()
        return True

    @PostgreSQL_wrapper(access_level=2, require_connection=True)
    async def count_rows(self, table_name: str) -> int:
        query = f"SELECT COUNT(*) AS count FROM {quote_ident(table_name)}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query)
        return row['count'] if row and 'count' in row else 0

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_user_by_chat_id(self, chat_id: int, table_name: str = "users") -> Result | None:
        query = f"SELECT user_id FROM {quote_ident(table_name)} WHERE chat_id @> $1 LIMIT 1"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, [chat_id])
        return row["user_id"] if row else None

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_interface_id_and_interface_type_by_student_number(
            self,
            student_number: int,
            bot_key: Optional[str] = None,  # Add the bot_key parameter
            table_name: str = "bot_interface_status"
    ) -> Result:
        # Start building the query
        query = f"""
            SELECT interface_id, interface_type, bot_key
            FROM {quote_ident(table_name)}
            WHERE metadata ->> 'student_number' = $1
        """

        # If bot_key is provided, add it to the WHERE clause
        if bot_key:
            query += " AND bot_key = $2"

        query += " LIMIT 1"  # Make sure to limit the result to 1 row

        # Now, execute the query with the appropriate parameters
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if bot_key:
                    row = await conn.fetchrow(query, str(student_number), bot_key)  # Pass both parameters
                else:
                    row = await conn.fetchrow(query, str(student_number))  # Only pass the student number

        if row:
            interface_id = row["interface_id"]
            interface_type = row["interface_type"]
            bot_key = row["bot_key"]
            return Result(
                True,
                "get_interface_id_and_interface_type_by_student_number",
                "",
                (interface_id, interface_type, bot_key)
            )

        return Result(False, "get_interface_id_and_interface_type_by_student_number",
                      "Did not find looked up student_number or bot_key", None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_interfaces_by_dining_params(
            self,
            auto_finder: str,  # The column name to check for in the 'dining' key
            auto_finder_value: bool,  # The value to match against the column
            bot_key: Optional[str] = None,  # Optional bot_key parameter
            table_name: str = "bot_interface_status"
    ) -> Result:
        # Safely quote the table name to prevent SQL injection
        quoted_auto_finder = quote_ident(auto_finder)

        # Start building the query
        query = f"""
            SELECT interface_id, interface_type, bot_key, created_at
            FROM {quote_ident(table_name)}
            WHERE metadata -> 'dining' IS NOT NULL
            AND metadata -> 'dining' ->> 'username' IS NOT NULL
            AND metadata -> 'dining' ->> 'password' IS NOT NULL
            AND (metadata -> 'dining' ->> $1)::boolean = $2  -- Parameterized dynamic key
        """

        # If bot_key is provided, add it to the WHERE clause
        if bot_key:
            query += " AND bot_key = $3"

        # Add ORDER BY clause to sort by created_at (ascending by default)
        query += " ORDER BY created_at ASC"

        # Execute the query with the appropriate parameters
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Fetch rows based on parameters
                if bot_key:
                    rows = await conn.fetch(query, auto_finder, auto_finder_value,
                                            bot_key)  # Fetch with both parameters
                else:
                    rows = await conn.fetch(query, auto_finder,
                                            auto_finder_value)  # Fetch with just the 'auto_finder_value'

        if rows:
            # Process the rows and return a Result with all matching interfaces
            interfaces = []
            for row in rows:
                interfaces.append((row["interface_id"], row["interface_type"], row["bot_key"]))

            return Result(
                True,
                "get_interfaces_by_dining_params",
                "",
                interfaces  # Return all matching interfaces with created_at sorted
            )

        return Result(False, "get_interfaces_by_dining_params",
                      "Did not find matching dining parameters", None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_enrollment_ids_by_user_id(self, user_id: int, table_name: str = "enrollments") -> Result:
        query = f"""
            SELECT id
            FROM {quote_ident(table_name)}
            WHERE user_id = $1
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(query, user_id)
        return Result(True, "get_enrollment_ids_by_user_id", "", [row["id"] for row in rows] if rows else [])

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_jsonb_key_or_nested_field(
            self,
            table_name: str,
            key_value: int,
            jsonb_column: str,
            primary_key: str,
            field: str = None,
            key_column: str = "user_id"
    ) -> Any:
        if field:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 ->> $2 AS result
                FROM {quote_ident(table_name)}
                WHERE {quote_ident(key_column)} = $3 AND {quote_ident(jsonb_column)} ? $4
            """
            params = (primary_key, field, key_value, primary_key)
        else:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 AS result
                FROM {quote_ident(table_name)}
                WHERE {quote_ident(key_column)} = $2 AND {quote_ident(jsonb_column)} ? $3
            """
            params = (primary_key, key_value, primary_key)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *params)

        return row["result"] if row else None

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_jsonb_key_or_nested_field_composite_key(
            self,
            table_name: str,
            user_id: int,
            chat_id: int,
            jsonb_column: str,
            primary_key: str,
            field: str = None
    ) -> Any:
        if field:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 ->> $2 AS result
                FROM {quote_ident(table_name)}
                WHERE chat_id = $3 AND user_id = $4 AND {quote_ident(jsonb_column)} ? $5
            """
            params = (primary_key, field, chat_id, user_id, primary_key)
        else:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 AS result
                FROM {quote_ident(table_name)}
                WHERE chat_id = $2 AND user_id = $3 AND {quote_ident(jsonb_column)} ? $4
            """
            params = (primary_key, chat_id, user_id, primary_key)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *params)

        return row["result"] if row else None

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def get_jsonb_by_array_match(
            self,
            table_name: str,
            array_column: str,
            match_value: int,
            jsonb_column: str,
            jsonb_key: str,
            nested_field: str = None
    ) -> Any:
        if nested_field:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 ->> $2 AS result
                FROM {quote_ident(table_name)}
                WHERE {quote_ident(array_column)} @> $3 AND {quote_ident(jsonb_column)} ? $4
            """
            params = (jsonb_key, nested_field, [match_value], jsonb_key)
        else:
            query = f"""
                SELECT {quote_ident(jsonb_column)} -> $1 AS result
                FROM {quote_ident(table_name)}
                WHERE {quote_ident(array_column)} @> $2 AND {quote_ident(jsonb_column)} ? $3
            """
            params = (jsonb_key, [match_value], jsonb_key)

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *params)
        return row["result"] if row else None

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def append_to_jsonb_array_field(
            self,
            table_name: str,
            key_value: Union[int, str],
            jsonb_column: str,
            new_items: list,
            key_column: str = "user_id"
    ) -> Result:

        query_check = f"""
            SELECT {quote_ident(jsonb_column)} 
            FROM {quote_ident(table_name)} 
            WHERE {quote_ident(key_column)} = $1
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query_check, key_value)
                if not row:
                    raise ValueError(f"No record found with {key_column}={key_value}")
                current_value = row[jsonb_column]

                if current_value is None:
                    raise ValueError(f"Field '{jsonb_column}' is NULL for {key_column}={key_value}")
                if not isinstance(current_value, list):
                    raise TypeError(f"Field '{jsonb_column}' is not a list for {key_column}={key_value}")

                query_update = f"""
                    UPDATE {quote_ident(table_name)}
                    SET {quote_ident(jsonb_column)} = {quote_ident(jsonb_column)} || $1::jsonb
                    WHERE {quote_ident(key_column)} = $2
                """

                await conn.execute(query_update, new_items, key_value)

        return Result(True, "append_to_jsonb_array_field", "", None)

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def fetch_one(self, query: str, *params):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.fetchrow(query, *params)

    @PostgreSQL_wrapper(access_level=8, require_connection=True)
    async def fetch_all(self, query: str, *params):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(query, *params)
                return [dict(r) for r in rows]

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def filter_jsonb_array_by_user_id(
            self,
            table_name: str,
            user_id: int,
            jsonb_column: str,
            filters: Dict[str, Tuple[str, Any]]
    ) -> list:
        where_clause, params = _decode_condition_set(filters)

        # Adjust param placeholders since user_id is $1, so filters start from $2
        # Replace all '%s' placeholders with appropriate numbered params starting from $2
        for i in range(len(params)):
            where_clause = where_clause.replace('%s', f'${i + 2}', 1)

        query = f"""
            SELECT jsonb_agg(elem) AS filtered_elements
            FROM (
                SELECT jsonb_array_elements({quote_ident(jsonb_column)}) AS elem
                FROM {quote_ident(table_name)}
                WHERE user_id = $1
            ) sub
            WHERE {where_clause}
        """

        values = [user_id] + params

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *values)

                if not row:
                    raise ValueError(f"No user found with user_id={user_id}")
                if row["filtered_elements"] is None:
                    raise ValueError(f"No matching elements found in '{jsonb_column}' for user_id={user_id}")

                return row["filtered_elements"]

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def filter_jsonb_array_by_chat_id(
            self,
            table_name: str,
            chat_id: int,
            jsonb_column: str,
            filters: Dict[str, Tuple[str, Any]]
    ) -> list:
        where_clause, params = _decode_condition_set(filters)

        # Fix param placeholders - starting from $2 since $1 is chat_id
        where_clause = where_clause.replace('%s', '$2')

        query = f"""
            SELECT jsonb_agg(elem) AS filtered_elements
            FROM (
                SELECT jsonb_array_elements({quote_ident(jsonb_column)}) AS elem
                FROM {quote_ident(table_name)}
                WHERE chat_id @> $1
            ) sub
            WHERE {where_clause}
        """

        values = [chat_id] + params

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query, *values)

                if not row:
                    raise ValueError(f"No user found with chat_id={chat_id}")
                if row["filtered_elements"] is None:
                    raise ValueError(f"No matching elements found in '{jsonb_column}' for chat_id={chat_id}")

                return row["filtered_elements"]

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def search_user_ids(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            limit: int = 100,
            table_name: str = "users"
    ) -> list[int]:

        scalar_fields = {"user_number", "national_code", "is_bot", "is_premium", "is_verified", "flag"}
        array_fields = {"chat_id"}
        jsonb_fields = {
            "first_name", "last_name", "username", "bio", "birthday", "language_code",
            "phone_number", "email", "address", "location", "gender", "activity", "profile_photo"
        }

        op_map = {
            '=': '=', '!=': '!=', '>': '>', '<': '<',
            '>=': '>=', '<=': '<=', 'ilike': 'ILIKE',
            'like': 'LIKE', 'in': 'IN', 'not in': 'NOT IN',
            'is': 'IS', 'is not': 'IS NOT', '~': '~', 'similar': 'SIMILAR TO'
        }

        where_clauses = []
        params = []

        for field, (op, value) in conditions.items():
            op = op.lower()
            if op not in op_map:
                raise ValueError(f"Unsupported operator: {op}")

            sql_op = op_map[op]
            field_quoted = quote_ident(field)

            if field in scalar_fields:
                where_clauses.append(f"{field_quoted} {sql_op} ${len(params) + 1}")
                params.append(value)

            elif field in array_fields:
                if sql_op in ('IN', 'NOT IN'):
                    placeholders = ', '.join(f"${i}" for i in range(len(params) + 1, len(params) + 1 + len(value)))
                    where_clauses.append(f"{field_quoted} {sql_op} ({placeholders})")
                    params.extend(value)
                else:
                    where_clauses.append(f"${len(params) + 1} = ANY({field_quoted})")
                    params.append(value)

            elif field in jsonb_fields:
                if fuzzy and isinstance(value, str):
                    where_clauses.append(f"""
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements({field_quoted}) AS elem
                        WHERE similarity(elem ->> '{field}', ${len(params) + 1}) > 0.4
                    )
                    """)
                    params.append(value)
                elif isinstance(value, (bool, int, float)):
                    where_clauses.append(f"""
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements({field_quoted}) AS elem
                        WHERE (elem ->> '{field}')::text {sql_op} ${len(params) + 1}
                    )
                    """)
                    params.append(str(value))
                else:
                    where_clauses.append(f"""
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements({field_quoted}) AS elem
                        WHERE elem ->> '{field}' {sql_op} ${len(params) + 1}
                    )
                    """)
                    params.append(value)
            else:
                raise ValueError(f"Unsupported or unknown field: {field}")

        where_sql = " AND ".join(f"({clause.strip()})" for clause in where_clauses)

        query = f"""
            SELECT user_id
            FROM {quote_ident(table_name)}
            WHERE {where_sql}
            LIMIT ${len(params) + 1}
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rowset = await conn.fetch(query, *params, limit)

        return [row["user_id"] for row in rowset if "user_id" in row]

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def delete_user_by_user_id(self, user_id: int, table_name: str = "users") -> None:
        query = f"DELETE FROM {quote_ident(table_name)} WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(query, user_id)

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def generate_unique_user_id(self, table_name: str = "users") -> int:
        import random
        query = f"SELECT COUNT(*) AS count FROM {quote_ident(table_name)} WHERE user_id = $1"
        async with self.pool.acquire() as conn:
            while True:
                user_id = random.randint(10 ** 11, 10 ** 12 - 1)  # 12-digit number
                async with conn.transaction():
                    row = await conn.fetchrow(query, user_id)
                    if row['count'] == 0:
                        return user_id

    @PostgreSQL_wrapper(access_level=5, require_connection=True)
    async def get_next_user_number(self, table_name: str = "users") -> int:
        query = f"SELECT MIN(user_number) AS min FROM {quote_ident(table_name)}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(query)
                min_number = row['min']
                if min_number is not None:
                    return min_number - 1
                raise ValueError(f"Unsupported output for next_user_number")

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def search_ids(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            fuzzy: bool = False,
            similarity_threshold: float = 0.4,
            limit: int = 100,
            table_name: str = "generic_table",
            id_column: str = "id",
            scalar_fields: set = None,
            array_fields: set = None,
            jsonb_fields: set = None,
            order_by: Optional[str] = None,
            descending: bool = False
    ) -> Result:
        """
        General-purpose row ID searcher for any table with scalar, array, or JSONB fields.
        Supports fuzzy text matching using pg_trgm similarity.
        """

        scalar_fields = scalar_fields or {"id"}
        array_fields = array_fields or set()
        jsonb_fields = jsonb_fields or set()

        op_map = {
            '=': '=', '!=': '!=', '>': '>', '<': '<',
            '>=': '>=', '<=': '<=', 'ilike': 'ILIKE',
            'like': 'LIKE', 'in': 'IN', 'not in': 'NOT IN',
            'is': 'IS', 'is not': 'IS NOT', '~': '~', 'similar': 'SIMILAR TO',
            '@>': '@>', 'contains': '@>',
            'count': '>=', 'count>=': '>=', 'count=': '='
        }

        where_clauses = []
        params = []

        for field, (op, value) in conditions.items():
            op = op.lower()
            if op not in op_map:
                raise ValueError(f"Unsupported operator: {op}")

            sql_op = op_map[op]
            field_quoted = quote_ident(field)

            if field in scalar_fields:
                if sql_op in ('IN', 'NOT IN'):
                    if not isinstance(value, (list, tuple, set)):
                        raise ValueError(f"Expected list/tuple for operator {sql_op} on field {field}")

                    placeholders = ', '.join(f"${i}" for i in range(len(params) + 1, len(params) + 1 + len(value)))
                    where_clauses.append(f"{field_quoted} {sql_op} ({placeholders})")
                    params.extend(value)

                elif fuzzy and isinstance(value, str):
                    where_clauses.append(f"similarity({field_quoted}, ${len(params) + 1}) > {similarity_threshold}")
                    params.append(value)
                else:
                    where_clauses.append(f"{field_quoted} {sql_op} ${len(params) + 1}")
                    params.append(value)

            elif field in array_fields:
                if op.startswith('count'):
                    if not isinstance(value, (tuple, list)) or len(value) != 2:
                        raise ValueError("Operator 'count' expects a (target_element, required_count) tuple")
                    target_elem, target_count = value

                    where_clauses.append(
                        f"(SELECT count(*) FROM unnest({field_quoted}) elem WHERE elem = ${len(params) + 1}) {sql_op} ${len(params) + 2}"
                    )
                    params.extend([target_elem, target_count])

                elif sql_op == '@>':
                    val_list = list(value) if isinstance(value, (list, tuple, set)) else [value]
                    where_clauses.append(f"{field_quoted} @> ${len(params) + 1}")
                    params.append(val_list)

                elif sql_op in ('IN', 'NOT IN'):
                    val_list = list(value) if isinstance(value, (list, tuple, set)) else [value]
                    placeholders = ', '.join(f"${i}" for i in range(len(params) + 1, len(params) + 1 + len(val_list)))
                    where_clauses.append(f"{field_quoted} {sql_op} ({placeholders})")
                    params.extend(val_list)  # Safely extends a list now

                else:
                    # Default ANY check: expects single scalar parameter
                    where_clauses.append(f"${len(params) + 1} = ANY({field_quoted})")
                    params.append(value)

            elif any(field.startswith(f"{jsonb_field}.") for jsonb_field in jsonb_fields):
                jsonb_field, nested_key = field.split(".", 1)
                field_quoted = quote_ident(jsonb_field)

                if fuzzy and isinstance(value, str):
                    where_clauses.append(
                        f"similarity({field_quoted} ->> '{nested_key}', ${len(params) + 1}) > {similarity_threshold}")
                    params.append(value)

                elif isinstance(value, (bool, int, float)):
                    where_clauses.append(
                        f"({field_quoted} ->> '{nested_key}')::text {sql_op} ${len(params) + 1}")
                    params.append(str(value))

                else:
                    where_clauses.append(
                        f"({field_quoted} ->> '{nested_key}') {sql_op} ${len(params) + 1}")
                    params.append(value)

            else:
                raise ValueError(f"Unsupported or unknown field: {field}")

        where_sql = " AND ".join(f"({clause.strip()})" for clause in where_clauses)

        order_clause = ""
        if order_by:
            order_clause = f"ORDER BY {quote_ident(order_by)} {'DESC' if descending else 'ASC'}"

        query = f"""
            SELECT {quote_ident(id_column)}
            FROM {quote_ident(table_name)}
            WHERE {where_sql}
            {order_clause}
            LIMIT ${len(params) + 1}
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rowset = await conn.fetch(query, *params, limit)

        return Result(True, "search_ids", "", [row[id_column] for row in rowset if id_column in row])

    @PostgreSQL_wrapper(access_level=4, require_connection=True)
    async def search_rows(
            self,
            conditions: Dict[str, Tuple[str, Any]],
            returning_columns: List[str] = None,
            fuzzy: bool = False,
            similarity_threshold: float = 0.4,
            limit: int = 100,
            table_name: str = "generic_table",
            scalar_fields: set = None,
            array_fields: set = None,
            jsonb_fields: set = None,
            order_by: Optional[str] = None,
            descending: bool = False
    ) -> Result:
        """
        General-purpose row searcher that returns specified columns.
        """
        # Default to returning just 'id' if nothing specified
        returning_columns = returning_columns or ["id"]
        scalar_fields = scalar_fields or set()
        array_fields = array_fields or set()
        jsonb_fields = jsonb_fields or set()

        op_map = {
            '=': '=', '!=': '!=', '>': '>', '<': '<',
            '>=': '>=', '<=': '<=', 'ilike': 'ILIKE',
            'like': 'LIKE', 'in': 'IN', 'not in': 'NOT IN',
            'is': 'IS', 'is not': 'IS NOT', '~': '~', 'similar': 'SIMILAR TO'
        }

        where_clauses = []
        params = []

        for field, (op, value) in conditions.items():
            op = op.lower()
            if op not in op_map:
                raise ValueError(f"Unsupported operator: {op}")

            sql_op = op_map[op]
            field_quoted = quote_ident(field)

            if field in scalar_fields:
                if sql_op in ('IN', 'NOT IN'):
                    if not isinstance(value, (list, tuple, set)):
                        raise ValueError(f"Expected list/tuple for operator {sql_op} on field {field}")

                    placeholders = ', '.join(f"${i}" for i in range(len(params) + 1, len(params) + 1 + len(value)))
                    where_clauses.append(f"{field_quoted} {sql_op} ({placeholders})")
                    params.extend(value)

                elif fuzzy and isinstance(value, str):
                    where_clauses.append(f"similarity({field_quoted}, ${len(params) + 1}) > {similarity_threshold}")
                    params.append(value)
                else:
                    where_clauses.append(f"{field_quoted} {sql_op} ${len(params) + 1}")
                    params.append(value)

            elif field in array_fields:
                if sql_op in ('IN', 'NOT IN'):
                    placeholders = ', '.join(f"${i}" for i in range(len(params) + 1, len(params) + 1 + len(value)))
                    where_clauses.append(f"{field_quoted} {sql_op} ({placeholders})")
                    params.extend(value)
                else:
                    where_clauses.append(f"${len(params) + 1} = ANY({field_quoted})")
                    params.append(value)

            elif any(field.startswith(f"{jsonb_field}.") for jsonb_field in jsonb_fields):
                jsonb_field, nested_key = field.split(".", 1)
                field_quoted = quote_ident(jsonb_field)

                if fuzzy and isinstance(value, str):
                    where_clauses.append(
                        f"similarity({field_quoted} ->> '{nested_key}', ${len(params) + 1}) > {similarity_threshold}")
                    params.append(value)

                elif isinstance(value, (bool, int, float)):
                    where_clauses.append(
                        f"({field_quoted} ->> '{nested_key}')::text {sql_op} ${len(params) + 1}")
                    params.append(str(value))

                else:
                    where_clauses.append(
                        f"({field_quoted} ->> '{nested_key}') {sql_op} ${len(params) + 1}")
                    params.append(value)

            else:
                raise ValueError(f"Unsupported or unknown field: {field}")

        # Build WHERE Clause
        if where_clauses:
            where_sql = " AND ".join(f"({clause.strip()})" for clause in where_clauses)
        else:
            where_sql = "TRUE"  # If no conditions, return everything up to limit

        # Build SELECT columns
        select_cols = ", ".join(quote_ident(col) for col in returning_columns)

        # Build ORDER BY
        order_clause = ""
        if order_by:
            order_clause = f"ORDER BY {quote_ident(order_by)} {'DESC' if descending else 'ASC'}"

        # Build Query
        query = f"""
            SELECT {select_cols}
            FROM {quote_ident(table_name)}
            WHERE {where_sql}
            {order_clause}
            LIMIT ${len(params) + 1}
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rowset = await conn.fetch(query, *params, limit)

        # Convert asyncpg Records to regular dicts
        result_data = [dict(row) for row in rowset]

        return Result(True, "search_rows", "", result_data)

    @PostgreSQL_wrapper
    async def update_jsonb_nested_by_keys(self,
                                          table_name: str,
                                          jsonb_column: str,
                                          json_path: Iterable[str],
                                          new_value: Any,
                                          conditions: Dict[str, Any],
                                          updated_at_column: str = "updated_at",
                                          log: bool = True):
        """
        Generic: UPDATE table
                SET jsonb_column = jsonb_set(jsonb_column, '{k1,k2,...}', $1::jsonb, true),
                    updated_at = NOW()
                WHERE <conditions...>;

        - json_path: iterable of keys, e.g. ("restrictions","limits","hour")
        - new_value: any JSON-serializable value (driver will handle -> cast to ::jsonb)
        - conditions: arbitrary PK/composite key, e.g. {"bot_key": "...", "interface_type": "...", "interface_id": 123}
        """
        where_sql, where_params = _build_conditions_sql_and_params(conditions)
        # Build the pg path '{k1,k2,...}'
        path_elems = ",".join([str(k).replace("'", "''") for k in json_path])
        path_literal = "{" + path_elems + "}"

        query = f"""
            UPDATE {table_name}
            SET {jsonb_column} = jsonb_set(COALESCE({jsonb_column}, '{{}}'::jsonb), %s, %s::jsonb, true),
                {updated_at_column} = NOW()
            {where_sql}
            RETURNING {jsonb_column}
        """

        # First param is path (text[]), we pass as Postgres text[] literal using ::text[] cast
        # asyncpg will send the string; Postgres interprets it as text[] via casting inside jsonb_set
        params = [path_literal, new_value, *where_params]
        return SQL(query), params

    @PostgreSQL_wrapper
    async def get_jsonb_nested_value_by_keys(self,
                                             table_name: str,
                                             jsonb_column: str,
                                             json_path: Iterable[str],
                                             conditions: Dict[str, Any],
                                             as_text: bool = False,
                                             log: bool = True):
        """
        Generic: SELECT <json> or <text> from jsonb by nested path.
        - If as_text=False -> use #> (jsonb)
        - If as_text=True  -> use #>> (text)
        """
        where_sql, where_params = _build_conditions_sql_and_params(conditions)
        path_elems = ",".join([str(k).replace("'", "''") for k in json_path])
        path_literal = "{" + path_elems + "}"
        op = "#>>" if as_text else "#>"

        query = f"""
            SELECT {jsonb_column} {op} %s AS value
            FROM {table_name}
            {where_sql}
            LIMIT 1
        """
        params = [path_literal, *where_params]
        return SQL(query), params

    @PostgreSQL_wrapper
    async def get_jsonb_key_or_field_by_keys(self,
                                             table_name: str,
                                             jsonb_column: str,
                                             primary_key: str,
                                             field: str | None,
                                             conditions: Dict[str, Any],
                                             log: bool = True):
        """
        Generic: fetch a top-level jsonb object at primary_key OR a field inside that object.
        - If field is None: returns the object (jsonb_column->primary_key)
        - Else: returns the object's field as text (jsonb_column->primary_key->>field)
        """
        where_sql, where_params = _build_conditions_sql_and_params(conditions)
        if field is None:
            # jsonb
            query = f"""
                SELECT {jsonb_column} -> %s AS value
                FROM {table_name}
                {where_sql}
                LIMIT 1
            """
            params = [primary_key, *where_params]
        else:
            # text
            query = f"""
                SELECT {jsonb_column} -> %s ->> %s AS value
                FROM {table_name}
                {where_sql}
                LIMIT 1
            """
            params = [primary_key, field, *where_params]
        return SQL(query), params

    @PostgreSQL_wrapper
    async def append_jsonb_array_by_keys(self,
                                         table_name: str,
                                         jsonb_column: str,
                                         json_path_to_array: Iterable[str],
                                         append_value: Any,
                                         conditions: Dict[str, Any],
                                         updated_at_column: str = "updated_at",
                                         log: bool = True):
        """
        Generic: append a JSON value to a jsonb array at path.
          If the target is NULL -> becomes []
          If target is not an array -> coerces to array [target] then appends
        """
        where_sql, where_params = _build_conditions_sql_and_params(conditions)
        path_elems = ",".join([str(k).replace("'", "''") for k in json_path_to_array])
        path_literal = "{" + path_elems + "}"

        # COALESCE to '[]' and handle non-array via jsonb_typeof guard:
        query = f"""
            UPDATE {table_name}
            SET {jsonb_column} = jsonb_set(
                    COALESCE({jsonb_column}, '{{}}'::jsonb),
                    %s,
                    CASE
                        WHEN jsonb_typeof({jsonb_column} #> %s) = 'array'
                            THEN ({jsonb_column} #> %s) || %s::jsonb
                        ELSE
                            COALESCE(({jsonb_column} #> %s), '[]'::jsonb) || %s::jsonb
                    END,
                    true
                ),
                {updated_at_column} = NOW()
            {where_sql}
            RETURNING {jsonb_column}
        """
        # We'll pass append_value as a single-element array JSON to be appended (e.g. '[value]')
        params = [
            path_literal,
            path_literal,
            path_literal,
            [append_value],  # driver will serialize as JSONB array
            path_literal,
            [append_value],
            *where_params
        ]
        return SQL(query), params


def _build_conditions_sql_and_params(conditions: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """
    Build a WHERE clause and params from an arbitrary conditions dict.
    Example -> ("WHERE col1=%s AND col2=%s", [v1, v2])
    """
    if not conditions:
        return "", []
    parts = []
    params = []
    for k, v in conditions.items():
        parts.append(f"{k}=%s")
        params.append(v)
    return " WHERE " + " AND ".join(parts), params


def quote_ident(name: str) -> str:
    # Double any existing quotes, then wrap in quotes
    return '"' + name.replace('"', '""') + '"'


def _decode_condition_set(filters: Dict[str, Tuple[str, Any]]) -> Tuple[str, List[Any]]:
    """
    Build SQL WHERE clause and param list for multiple conditions on jsonb array elements.
    Raises errors for unsupported operators or invalid input formats.
    """
    op_map = {
        '=': '=', '!=': '!=', '>': '>', '<': '<',
        '>=': '>=', '<=': '<=',
        'ilike': 'ILIKE', 'like': 'LIKE',
        'in': 'IN', 'not in': 'NOT IN',
        'is': 'IS', 'is not': 'IS NOT'
    }

    if not isinstance(filters, dict):
        raise ValueError("Filters must be a dictionary of {field_path: (operator, value)}")

    clauses = []
    params = []

    for path, condition in filters.items():
        if not isinstance(condition, tuple) or len(condition) != 2:
            raise ValueError(f"Condition for '{path}' must be a tuple (operator, value)")

        operator, value = condition
        operator = operator.lower()

        if operator not in op_map:
            raise ValueError(f"Unsupported operator: '{operator}' in condition for '{path}'")

        sql_op = op_map[operator]

        if sql_op in ('IN', 'NOT IN'):
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"Value for '{sql_op}' must be a list or tuple for path '{path}'")
            placeholders = ', '.join(['%s'] * len(value))
            clauses.append(f"(elem ->> '{path}') {sql_op} ({placeholders})")
            params.extend(value)
        else:
            if sql_op in ('>', '<', '>=', '<='):
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Numeric comparison operator '{sql_op}' used with non-numeric value '{value}' for field '{path}'")
                clauses.append(f"(elem ->> '{path}')::numeric {sql_op} %s")
                params.append(value)
            elif isinstance(value, bool):
                # Safely cast JSONB boolean using to_jsonb
                clauses.append(f"(elem -> '{path}') {sql_op} to_jsonb(%s)")
                params.append(value)
            else:
                # Default string comparison
                clauses.append(f"(elem ->> '{path}') {sql_op} %s")
                params.append(str(value))

    where_clause = ' AND '.join(clauses)
    return where_clause, params
