"""PostgreSQL database client (for calculation history)."""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text, Column, BigInteger, Integer, String, DateTime, JSON, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
import structlog

logger = structlog.get_logger()

Base = declarative_base()


class User(Base):
    """User model for storing Telegram user data."""
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    language_code = Column(String(10), nullable=True)
    agreement_accepted = Column(DateTime(timezone=True), nullable=True)  # Timestamp when agreement was accepted
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Calculation(Base):
    """Calculation model for storing calculation results."""
    __tablename__ = "calculations"

    calculation_id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(BigInteger, nullable=False, index=True)
    article_id = Column(BigInteger, nullable=False, index=True)
    calculation_type = Column(String(20), nullable=False)
    tn_ved_code = Column(String(10), nullable=True)
    express_result = Column(JSONB, nullable=True)
    detailed_result = Column(JSONB, nullable=True)
    status = Column(String(10), nullable=False)
    calculated_basket = Column(Integer, nullable=True)  # Calculated basket number
    actual_basket = Column(Integer, nullable=True)  # Actual working basket number
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        CheckConstraint("calculation_type IN ('express', 'detailed')", name="check_calculation_type"),
        CheckConstraint("status IN ('🟢', '🟡', '🟠', '🔴', 'pending', 'processing', 'completed', 'failed', 'blocked', 'orange_zone')", name="check_status"),
    )


class DatabaseClient:
    """PostgreSQL database client."""

    def __init__(self, database_url: str):
        """
        Initialize database client.

        Args:
            database_url: PostgreSQL connection URL (asyncpg format)
        """
        self.database_url = database_url
        self.engine = None
        self.session_factory: Optional[async_sessionmaker] = None

    async def connect(self):
        """Connect to database and create tables."""
        try:
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_pre_ping=True
            )
            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            # Create tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            # Run migrations for new columns
            await self._migrate_basket_columns()
            
            # Test connection
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("database_connected", database_url=self.database_url.split("@")[-1])
        except Exception as e:
            logger.error("database_connection_failed", error=str(e))
            raise
    
    async def _migrate_basket_columns(self):
        """Migrate basket columns if they don't exist."""
        try:
            async with self.engine.begin() as conn:
                # Check if columns exist
                check_query = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'calculations' 
                    AND column_name IN ('calculated_basket', 'actual_basket')
                """)
                result = await conn.execute(check_query)
                existing_columns = {row[0] for row in result.fetchall()}
                
                # Add calculated_basket if not exists
                if 'calculated_basket' not in existing_columns:
                    alter_query1 = text("""
                        ALTER TABLE calculations 
                        ADD COLUMN calculated_basket INTEGER
                    """)
                    await conn.execute(alter_query1)
                    logger.info("migration_calculated_basket_added")
                
                # Add actual_basket if not exists
                if 'actual_basket' not in existing_columns:
                    alter_query2 = text("""
                        ALTER TABLE calculations 
                        ADD COLUMN actual_basket INTEGER
                    """)
                    await conn.execute(alter_query2)
                    logger.info("migration_actual_basket_added")
        except Exception as e:
            # Log but don't fail - migration errors shouldn't break app startup
            logger.warning("migration_basket_columns_failed", error=str(e))

    async def disconnect(self):
        """Disconnect from database."""
        if self.engine:
            await self.engine.dispose()
            logger.info("database_disconnected")

    async def get_session(self) -> AsyncSession:
        """
        Get database session.

        Returns:
            AsyncSession instance
        """
        if not self.session_factory:
            raise RuntimeError("Database not connected")
        return self.session_factory()

    async def save_or_update_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
        agreement_accepted: Optional[datetime] = None
    ) -> None:
        """
        Save or update user data.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            first_name: User first name
            last_name: User last name
            language_code: User language code
            agreement_accepted: Timestamp when agreement was accepted (None to not update)
        """
        session = await self.get_session()
        try:
            try:
                from sqlalchemy import select
                result = await session.execute(select(User).where(User.user_id == user_id))
                user = result.scalar_one_or_none()

                if user:
                    # Update existing user
                    user.username = username
                    user.first_name = first_name
                    user.last_name = last_name
                    user.language_code = language_code
                    if agreement_accepted is not None:
                        user.agreement_accepted = agreement_accepted
                    user.updated_at = datetime.utcnow()
                else:
                    # Create new user
                    user = User(
                        user_id=user_id,
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        language_code=language_code,
                        agreement_accepted=agreement_accepted
                    )
                    session.add(user)

                await session.commit()
                logger.debug("user_saved", user_id=user_id, username=username, agreement_accepted=agreement_accepted is not None)
            except Exception as e:
                await session.rollback()
                logger.error("user_save_failed", user_id=user_id, error=str(e))
                raise
        finally:
            await session.close()

    async def save_calculation(
        self,
        calculation_id: str,
        user_id: int,
        article_id: int,
        calculation_type: str,
        status: str,
        tn_ved_code: Optional[str] = None,
        express_result: Optional[Dict[str, Any]] = None,
        detailed_result: Optional[Dict[str, Any]] = None,
        calculated_basket: Optional[int] = None,
        actual_basket: Optional[int] = None
    ) -> None:
        """
        Save or update calculation result to database.
        If calculation exists, updates it (e.g., adds detailed_result to express calculation).

        Args:
            calculation_id: Unique calculation ID
            user_id: Telegram user ID
            article_id: WB article ID
            calculation_type: Type of calculation (express or detailed)
            status: Calculation status
            tn_ved_code: TN VED code
            express_result: Express calculation result data
            detailed_result: Detailed calculation result data
        """
        session = await self.get_session()
        try:
            try:
                from sqlalchemy import select
                # Check if calculation already exists
                result = await session.execute(select(Calculation).where(Calculation.calculation_id == calculation_id))
                existing_calc = result.scalar_one_or_none()

                if existing_calc:
                    # Update existing calculation
                    if express_result is not None:
                        existing_calc.express_result = express_result
                    if detailed_result is not None:
                        existing_calc.detailed_result = detailed_result
                    if calculation_type:
                        existing_calc.calculation_type = calculation_type
                    if status:
                        existing_calc.status = status
                    if tn_ved_code is not None:
                        existing_calc.tn_ved_code = tn_ved_code
                    if calculated_basket is not None:
                        existing_calc.calculated_basket = calculated_basket
                    if actual_basket is not None:
                        existing_calc.actual_basket = actual_basket
                    logger.debug("calculation_updated", calculation_id=calculation_id, user_id=user_id, article_id=article_id)
                else:
                    # Create new calculation
                    calculation = Calculation(
                        calculation_id=calculation_id,
                        user_id=user_id,
                        article_id=article_id,
                        calculation_type=calculation_type,
                        tn_ved_code=tn_ved_code,
                        express_result=express_result,
                        detailed_result=detailed_result,
                        status=status,
                        calculated_basket=calculated_basket,
                        actual_basket=actual_basket
                    )
                    session.add(calculation)
                    logger.debug("calculation_saved", calculation_id=calculation_id, user_id=user_id, article_id=article_id)
                
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error("calculation_save_failed", calculation_id=calculation_id, user_id=user_id, error=str(e))
                raise
        finally:
            await session.close()

    async def get_mau(self) -> int:
        """
        Get Monthly Active Users (MAU) - users who made at least one calculation in the last 30 days.
        
        Returns:
            Number of unique users with calculations in the last 30 days
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT COUNT(DISTINCT user_id) as mau
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '30 days'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            await session.close()

    async def get_wau(self) -> int:
        """
        Get Weekly Active Users (WAU) - users who made at least one calculation in the last 7 days.
        
        Returns:
            Number of unique users with calculations in the last 7 days
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT COUNT(DISTINCT user_id) as wau
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            await session.close()

    async def get_dau(self) -> int:
        """
        Get Daily Active Users (DAU) - users who made at least one calculation in the last 24 hours.
        
        Returns:
            Number of unique users with calculations in the last 24 hours
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT COUNT(DISTINCT user_id) as dau
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            await session.close()

    async def get_new_users_24h(self) -> int:
        """
        Get number of new users registered in the last 24 hours.
        
        Returns:
            Number of new users in the last 24 hours
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT COUNT(*) as new_users
                FROM users
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            await session.close()

    async def get_calculations_24h_by_status(self) -> Dict[str, int]:
        """
        Get number of calculations in the last 24 hours grouped by status.
        
        Returns:
            Dictionary with status as key and count as value
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT status, COUNT(*) as count
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY status
            """)
            result = await session.execute(query)
            rows = result.fetchall()
            status_counts = {row[0]: row[1] for row in rows}
            return status_counts
        finally:
            await session.close()

    async def get_total_calculations_24h(self) -> int:
        """
        Get total number of calculations in the last 24 hours.
        
        Returns:
            Total number of calculations in the last 24 hours
        """
        session = await self.get_session()
        try:
            query = text("""
                SELECT COUNT(*) as total
                FROM calculations
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            result = await session.execute(query)
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            await session.close()

