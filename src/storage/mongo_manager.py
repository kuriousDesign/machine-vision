from pymongo import MongoClient
from config import MONGO_URI

class MongoManager:
    def __init__(self):
        self.client = MongoClient(MONGO_URI)
        self.db = self.client["machine"]
        self.parts = self.db["parts"]

    def insert_or_update_part(self, serialNumber: str, data: dict):
        self.parts.update_one(
            {"serialNumber": serialNumber},
            {"$set": {"data": data}},
            upsert=True
        )
