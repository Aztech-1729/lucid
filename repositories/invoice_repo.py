from datetime import datetime
from typing import Optional
from database.mongo import db
from models.invoice import Invoice


class InvoiceRepository:
    def __init__(self):
        self.collection = db.invoices if db is not None else None

    async def create(self, invoice: Invoice) -> Invoice:
        if self.collection is not None:
            await self.collection.insert_one(invoice.model_dump())
        return invoice

    async def get_by_order_id(self, order_id: str) -> Optional[Invoice]:
        if self.collection is None:
            return None
        data = await self.collection.find_one({"order_id": order_id})
        if data:
            return Invoice(**data)
        return None

    async def update_status(self, order_id: str, status: str) -> bool:
        if self.collection is None:
            return False
        update_data = {"status": status}
        if status == "paid":
            update_data["paid_at"] = datetime.utcnow()
            
        res = await self.collection.update_one(
            {"order_id": order_id},
            {"$set": update_data}
        )
        return res.modified_count > 0


invoice_repo = InvoiceRepository()
