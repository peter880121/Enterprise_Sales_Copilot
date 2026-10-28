from sqlalchemy import func, or_, select, update

from app.auth.models import User
from app.crm.models import Account, Contact


class CRMRepository:
    def __init__(self, session):
        self.session = session

    def get(self, model, entity_id, *, lock=False):
        query = select(model).where(model.id == entity_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def list(self, model, query):
        filters = []
        if query.is_active is not None:
            filters.append(model.is_active == query.is_active)
        if model is Account and query.owner_id:
            filters.append(Account.owner_id == str(query.owner_id))
        if model is Contact and query.account_id:
            filters.append(Contact.account_id == str(query.account_id))
        if query.q:
            columns = [model.name] if model is Account else [Contact.name, Contact.email]
            filters.append(or_(*(column.contains(query.q, autoescape=True) for column in columns)))
        total = self.session.scalar(select(func.count()).select_from(model).where(*filters))
        order = getattr(model, getattr(query, "sort", "name"))
        rows = self.session.scalars(
            select(model)
            .where(*filters)
            .order_by(order, model.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        ).all()
        return rows, total

    def cas(self, model, entity_id, version, values):
        return (
            self.session.execute(
                update(model)
                .where(model.id == entity_id, model.version == version)
                .values(**values, version=version + 1)
                .execution_options(synchronize_session=False)
            ).rowcount
            == 1
        )

    def owner(self, owner_id):
        return self.get(User, owner_id, lock=True)
