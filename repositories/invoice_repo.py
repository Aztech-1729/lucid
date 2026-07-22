from datetime import datetime
from typing import Optional
from database.mongo import get_db
from models.invoice import Invoice


class InvoiceRepository:
    @property
    def collection(self):
        return get_db().invoices

    async def create(self, invoice: Invoice) -> Invoice:
        await self.collection.insert_one(invoice.model_dump())
        return invoice

    async def get_by_order_id(self, order_id: str) -> Optional[Invoice]:
        data = await self.collection.find_one({"order_id": order_id})
        if data:
            return Invoice(**data)
        return None

    async def update_status(self, order_id: str, status: str) -> bool:
        update_data = {"status": status}
        if status == "paid":
            update_data["paid_at"] = datetime.utcnow()
            
        res = await self.collection.update_one(
            {"order_id": order_id},
            {"$set": update_data}
        )
        return res.modified_count > 0


invoice_repo = InvoiceRepository()
