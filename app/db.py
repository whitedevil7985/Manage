from psycopg_pool import AsyncConnectionPool

class Database:
    def __init__(self, database_url: str):
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        self.pool = AsyncConnectionPool(
            conninfo=database_url, min_size=1, max_size=5, open=False,
            kwargs={"autocommit": True},
        )

    async def open(self):
        await self.pool.open()
        await self.pool.wait()
        async with self.pool.connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS heroku_accounts (
                    id BIGSERIAL PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    token_encrypted TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

    async def close(self):
        await self.pool.close()

    async def add_account(self, label: str, encrypted_token: str):
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO heroku_accounts (label, token_encrypted) VALUES (%s, %s)",
                (label, encrypted_token),
            )

    async def get_accounts(self):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, label, token_encrypted FROM heroku_accounts ORDER BY label"
            )
            return await cur.fetchall()

    async def get_account(self, label: str):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, label, token_encrypted FROM heroku_accounts WHERE lower(label)=lower(%s)",
                (label,),
            )
            return await cur.fetchone()

    async def remove_account(self, label: str) -> bool:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM heroku_accounts WHERE lower(label)=lower(%s)", (label,)
            )
            return cur.rowcount > 0
