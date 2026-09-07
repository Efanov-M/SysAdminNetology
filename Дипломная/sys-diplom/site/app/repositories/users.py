from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    def get_by_login(self, login: str) -> User | None:
        return self.db.scalar(select(User).where(User.login == login))

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))

    def get_by_login_or_email(self, identity: str) -> User | None:
        return self.get_by_login(identity) or self.get_by_email(identity)


def users_repository(db: Session) -> UserRepository:
    return UserRepository(db)
