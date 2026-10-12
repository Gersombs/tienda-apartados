import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.database import db_manager
from sqlalchemy import Date, DateTime, MetaData, Table, func, select
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError

logger = logging.getLogger(__name__)

MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "mock_data"
SEED_ORDER = {
    "categories": 10,
    "delivery_points": 10,
    "store_settings": 10,
    "private_settings": 10,
    "products": 20,
    "delivery_slots": 20,
    "product_variants": 30,
    "product_images": 30,
}

PRODUCTION_SEED_TABLES = (
    "categories",
    "delivery_points",
    "store_settings",
    "products",
    "delivery_slots",
    "product_variants",
    "product_images",
)


async def initialize_mock_data():
    """Populate tables with mock JSON data when they are empty."""
    if not db_manager.engine:
        logger.warning("Database engine is not ready; skipping mock data initialization")
        return

    if not MOCK_DATA_DIR.exists():
        logger.info("mock_data directory not found, skipping mock initialization")
        return

    data_files = sorted(
        MOCK_DATA_DIR.glob("*.json"),
        key=lambda path: (SEED_ORDER.get(path.stem, 100), path.name),
    )
    if not data_files:
        logger.info("No mock JSON files detected; skipping mock initialization")
        return

    # Foreign keys require parent tables to be populated first. Sequential
    # loading is startup-only and deterministic, which is preferable to racing
    # seed inserts across independent transactions.
    for data_file in data_files:
        try:
            await _load_table_from_file(data_file)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Unexpected error loading %s: %s", data_file.name, exc)


async def initialize_production_catalog() -> dict[str, int]:
    """Seed the publishable catalog once, atomically, without private data.

    A completely empty target set is populated in one transaction. A fully
    populated set is an idempotent no-op. Mixed state is rejected because seed
    IDs could otherwise attach children to unrelated existing rows.
    """

    if db_manager.engine is None:
        raise RuntimeError("La base de datos no está inicializada.")

    async with db_manager.engine.begin() as conn:
        tables: dict[str, Table] = {}
        counts: dict[str, int] = {}
        for table_name in PRODUCTION_SEED_TABLES:
            tables[table_name] = await _reflect_table(conn, table_name)
            counts[table_name] = int(
                await conn.scalar(select(func.count()).select_from(tables[table_name])) or 0
            )

        populated = [name for name, count in counts.items() if count > 0]
        empty = [name for name, count in counts.items() if count == 0]
        if populated and empty:
            raise RuntimeError(
                "El catálogo está parcialmente inicializado; no se insertó nada. "
                f"Con datos: {', '.join(populated)}. Vacías: {', '.join(empty)}."
            )
        if populated:
            return {name: 0 for name in PRODUCTION_SEED_TABLES}

        inserted: dict[str, int] = {}
        for table_name in PRODUCTION_SEED_TABLES:
            data_file = MOCK_DATA_DIR / f"{table_name}.json"
            raw_records = json.loads(data_file.read_text(encoding="utf-8"))
            records = _prepare_records(raw_records, tables[table_name])
            if not records:
                raise RuntimeError(f"La semilla {data_file.name} no contiene filas válidas.")
            await conn.execute(tables[table_name].insert(), records)
            inserted[table_name] = len(records)
        return inserted


def _prepare_records(raw_data: Any, table: Table) -> list[dict[str, Any]]:
    """Filter JSON payload to match the table definition and coerce values."""
    if isinstance(raw_data, dict):
        records_iterable: Iterable[dict[str, Any]] = [raw_data]
    elif isinstance(raw_data, list):
        records_iterable = [item for item in raw_data if isinstance(item, dict)]
    else:
        return []

    column_map = {column.name: column for column in table.columns}
    prepared: list[dict[str, Any]] = []

    for entry in records_iterable:
        filtered = {}
        for key, value in entry.items():
            if key not in column_map:
                continue
            column = column_map[key]
            typed_value = _coerce_temporal_value(value, column)
            filtered[key] = _coerce_value(typed_value, column)
        if filtered:
            prepared.append(filtered)

    return prepared


def _coerce_temporal_value(value: Any, column) -> Any:
    """Convert ISO-like strings to Date/DateTime objects when needed."""
    if value is None or not isinstance(value, str):
        return value

    column_type = column.type
    if isinstance(column_type, Date):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return value

    if isinstance(column_type, DateTime):
        val_wo_z = value.replace("Z", "+00:00")
        for parser in (lambda v: datetime.fromisoformat(v), lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S")):
            try:
                return parser(val_wo_z)
            except ValueError:
                continue
        return value

    return value


def _coerce_value(value: Any, column) -> Any:
    """Coerce nested structures to JSON strings when the column is not JSON."""
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        visit_name = getattr(column.type, "__visit_name__", "").lower()
        if "json" in visit_name:
            return value
        return json.dumps(value, ensure_ascii=False)

    return value


async def _reflect_table(conn, table_name: str) -> Table:
    """Reflect a table definition inside a synchronous context."""

    def _reflect(sync_conn):
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=sync_conn)

    return await conn.run_sync(_reflect)


async def _load_table_from_file(data_file: Path):
    table_name = data_file.stem
    logger.info("Processing mock data file %s for table %s", data_file.name, table_name)

    async with db_manager.engine.begin() as conn:
        try:
            table = await _reflect_table(conn, table_name)
        except NoSuchTableError:
            logger.warning("Table %s does not exist; skipping %s", table_name, data_file.name)
            return
        except SQLAlchemyError as exc:
            logger.error("Failed to reflect table %s: %s", table_name, exc)
            return

        row_count = await conn.scalar(select(func.count()).select_from(table))
        if row_count and row_count > 0:
            logger.info("Table %s already has %d rows; skipping mock insert", table_name, row_count)
            return

        try:
            raw_records = json.loads(data_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in %s: %s", data_file.name, exc)
            return

        records = _prepare_records(raw_records, table)
        if not records:
            logger.warning("No valid records found in %s after preparing data", data_file.name)
            return

        try:
            await conn.execute(table.insert(), records)
            logger.info("Inserted %d mock records into %s", len(records), table_name)
        except SQLAlchemyError as exc:
            logger.error("Failed to insert mock data into %s: %s", table_name, exc)
