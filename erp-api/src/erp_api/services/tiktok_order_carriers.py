"""Resolve official carrier names without mixing different packages."""
from collections.abc import Mapping


def carrier_name(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def package_carrier(package, lines, order_provider, *, single_package):
    explicit = carrier_name(package.get("shipping_provider_name")) or carrier_name(package.get("carrier_name"))
    if explicit:
        return explicit
    package_id = package.get("id") or package.get("package_id")
    matching = [line for line in lines if isinstance(line, Mapping) and line.get("package_id") == package_id]
    names = {name for line in matching if (name := carrier_name(line.get("shipping_provider_name"))
             or carrier_name(line.get("carrier_name")))}
    if names:
        return next(iter(names)) if len(names) == 1 else None
    if not single_package:
        return None
    unnamed = [line for line in lines if isinstance(line, Mapping) and not line.get("package_id")]
    names = {name for line in unnamed if (name := carrier_name(line.get("shipping_provider_name"))
             or carrier_name(line.get("carrier_name")))}
    if names:
        return next(iter(names)) if len(names) == 1 else None
    return carrier_name(order_provider)


def names_by_package(fulfillments):
    names = {}
    for fulfillment in fulfillments:
        name = carrier_name(fulfillment.carrier)
        if name:
            names.setdefault(fulfillment.platform_package_id, set()).add(name)
    return {package: next(iter(values)) for package, values in names.items() if len(values) == 1}
