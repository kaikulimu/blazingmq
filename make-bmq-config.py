import itertools

from blazingmq.dev.configurator.configurator import Configurator
from blazingmq.dev.configurator.localsite import LocalSite


configurator = Configurator()
instance = itertools.count(start=1)
port_allocator = itertools.count(start=40000)
cluster = configurator.cluster(
    name="c2x2",
    nodes=[
        configurator.broker(
            name="east1",
            instance=str(next(instance)),
            tcp_host="localhost",
            tcp_port=next(port_allocator),
            data_center="east",
        ),
        configurator.broker(
            name="east2",
            instance=str(next(instance)),
            tcp_host="localhost",
            tcp_port=next(port_allocator),
            data_center="east",
        ),
        configurator.broker(
            name="west1",
            instance=str(next(instance)),
            tcp_host="localhost",
            tcp_port=next(port_allocator),
            data_center="west",
        ),
        configurator.broker(
            name="west2",
            instance=str(next(instance)),
            tcp_host="localhost",
            tcp_port=next(port_allocator),
            data_center="west",
        ),
    ],
)
cluster.priority_domain("bmq.test.mmap.priority")
configurator.broker(
    name="eastp",
    instance=str(next(instance)),
    tcp_host="localhost",
    tcp_port=next(port_allocator),
    data_center="east",
).proxy(cluster)

for broker in configurator.brokers.values():
    configurator.deploy(broker, LocalSite(f"/Users/yyan82/Desktop/tmp/bmq-config/{broker.name}"))
