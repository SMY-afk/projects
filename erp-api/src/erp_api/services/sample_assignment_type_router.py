"""One assignment event, one destination table; read both tables for workloads."""

from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordResult,
)


class SampleAssignmentTypeRouter:
    def __init__(self, free, refundable):
        self.free = free
        self.refundable = refundable

    async def sync(self, **scope):
        free = await self.free.sync(**scope)
        paid = await self.refundable.sync(**scope)
        return SampleAssignmentRecordResult(
            free.created_count + paid.created_count, free.updated_count + paid.updated_count
        )


class CombinedAssignmentReader:
    def __init__(self, *clients):
        self.clients = clients

    async def list_record_snapshots(self):
        records = []
        seen = set()
        for client in self.clients:
            for record in await client.list_record_snapshots():
                number = record.snapshot.fields.get("分配编号")
                if isinstance(number, str) and number:
                    if number in seen:
                        raise RuntimeError("Assignment event is duplicated across type tables")
                    seen.add(number)
                records.append(record)
        return tuple(records)
