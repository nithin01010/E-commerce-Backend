import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.role import Role
from app.core.security import get_password_hash

async def init_db():
    async with AsyncSessionLocal() as db:
        # 1. Create Default Roles
        roles = ["customer", "seller", "admin"]
        for role_name in roles:
            result = await db.execute(select(Role).where(Role.name == role_name))
            role = result.scalars().first()
            if not role:
                new_role = Role(name=role_name)
                db.add(new_role)
                print(f"Created role: {role_name}")
        
        await db.commit()

        # 2. Create Admin Account
        admin_email = "admin@example.com"
        result = await db.execute(select(User).where(User.email == admin_email))
        admin_user = result.scalars().first()

        if not admin_user:
            # Get the admin role ID that was just created
            result = await db.execute(select(Role).where(Role.name == "admin"))
            admin_role = result.scalars().first()

            if admin_role:
                new_admin = User(
                    email=admin_email,
                    # Securely hash the default password
                    password=get_password_hash("Admin123!"),
                    role_id=admin_role.id,
                    is_active=True
                )
                db.add(new_admin)
                await db.commit()
                print(f"Created admin user: {admin_email}")

if __name__ == "__main__":
    print("Starting database initialization...")
    asyncio.run(init_db())
    print("Database initialization finished.")
