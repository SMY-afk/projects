"""Independent allocation pools; creator affinity is checked by the transaction."""

from erp_api.services.sample_assignment_workload_delta import (
    apply_assignment_to_workloads,
)
from erp_api.services.sample_bd_assignment import validate_bd_roster


async def run_type_pools(service, pending, tenant_id, shop_id):
    from erp_api.services.sample_auto_assignment_service import (
        SampleAutoAssignmentRunResult,
    )

    results = []
    invalid_roster = False
    for sample_type in ("free", "refundable"):
        requests = [
            request for request in pending if request.sample_type == sample_type
        ]
        if not requests:
            continue
        workloads = tuple(
            await service._roster_provider.list_members(
                tenant_id,
                shop_id,
                sample_type=sample_type,
            )
        )
        try:
            validate_bd_roster(workloads)
        except ValueError:
            invalid_roster = True
            for request in requests:
                results.append(await service._record_blocked(request, "roster_invalid"))
            continue
        for request in requests:
            blocked_reason = await service._image_gate.blocked_reason(
                request.tenant_id,
                request.shop_id,
                request.application_id,
            )
            result = (
                await service._record_blocked(request, blocked_reason)
                if blocked_reason is not None
                else await service._assign_one(request, workloads)
            )
            results.append(result)
            if result.decision is not None and result.decision.assigned:
                workloads = apply_assignment_to_workloads(workloads, result.decision)
    return SampleAutoAssignmentRunResult(
        status="blocked" if invalid_roster else "succeeded",
        items=tuple(results),
        blocked_reason="roster_invalid" if invalid_roster else None,
    )
