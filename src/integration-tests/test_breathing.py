# Copyright 2024 Bloomberg Finance L.P.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This test suite exercises basic routing functionality to in the presence of all
types of queues.
"""

from collections import namedtuple

import blazingmq.dev.it.testconstants as tc
from blazingmq.dev.it.fixtures import (  # pylint: disable=unused-import
    Cluster,
    cartesian_product_cluster,
    cluster,
    order,
    multi_node,
    multi_interface,
    start_cluster,
    tweak,
)
from blazingmq.dev.it.process.client import Client
from blazingmq.dev.it.util import wait_until

pytestmark = order(1)

BmqClient = namedtuple("BmqClient", "handle, uri")


def _close_clients(clients, uris):
    for client, uri in zip(clients, uris):
        assert client.close(uri, block=True) == Client.e_SUCCESS


def _stop_clients(clients):
    for client in clients:
        assert client.stop_session(block=True) == Client.e_SUCCESS


def _verify_delivery(consumer, uri, messages, timeout=2):
    consumer.wait_push_event()
    assert wait_until(
        lambda: len(consumer.list(uri, block=True)) == len(messages), timeout
    )
    consumer.list(uri, block=True)


def _verify_delivery_and_confirm(consumer, uri, messages):
    _verify_delivery(consumer, uri, messages)
    assert consumer.confirm(uri, "*", block=True) == Client.e_SUCCESS


def _verify_delivery_and_confirm_balanced(consumer, uris, messages, timeout=3):
    consumer.wait_push_event()

    def wait_cond():
        return sum(map(lambda u: len(consumer.list(u, block=True)), uris)) == len(
            messages
        )

    assert wait_until(wait_cond, timeout)

    msgs = []
    for uri in uris:
        uri_msgs = consumer.list(uri, block=True)

        # Ensure each uri has received part of messages
        assert len(uri_msgs) > 0

        msgs.extend(uri_msgs)

    # We cannot rely on the order of incoming messages so we just sort both lists
    messages.sort()
    msgs.sort(key=lambda msg: msg.payload)

    for i, message in enumerate(messages):
        assert msgs[i].payload == message

    for uri in uris:
        assert consumer.confirm(uri, "*", block=True) == Client.e_SUCCESS


def _verify_max_messages_max_bytes_routing(producer, consumer, other_consumers):
    # Verify no messages when we start

    try:
        assert len(consumer.handle.list(consumer.uri, block=True)) == 0
    except RuntimeError:
        pass  # No messages, that's what we want

    # verify maxUnconfirmedBytes. Post message exceeding max
    assert (
        producer.handle.post(
            producer.uri,
            payload=["123"],
            block=True,
            wait_ack=True,
        )
        == Client.e_SUCCESS
    )

    _verify_delivery(consumer.handle, consumer.uri, ["123"])
    # not confirming

    for anotherConsumer in other_consumers:
        _verify_delivery_and_confirm(
            anotherConsumer.handle, anotherConsumer.uri, ["123"]
        )

    assert (
        producer.handle.post(producer.uri, payload=["1"], block=True, wait_ack=True)
        == Client.e_SUCCESS
    )

    for anotherConsumer in other_consumers:
        _verify_delivery_and_confirm(anotherConsumer.handle, anotherConsumer.uri, ["1"])

    # consumer is over maxUnconfirmedBytes (3)
    # assert no PUSH received within 1 second
    assert not consumer.handle.outputs_regex("MESSAGE.*PUSH", timeout=1)
    msgs = consumer.handle.list(consumer.uri, block=True)
    assert len(msgs) == 1
    assert msgs[0].payload == "123"

    assert consumer.handle.confirm(consumer.uri, "*", block=True) == Client.e_SUCCESS

    # onHandleUsable kicks in
    _verify_delivery(consumer.handle, consumer.uri, ["1"])
    # not confirming

    # verify maxUnconfirmedMessages
    assert (
        producer.handle.post(producer.uri, payload=["2"], block=True, wait_ack=True)
        == Client.e_SUCCESS
    )

    for anotherConsumer in other_consumers:
        _verify_delivery_and_confirm(anotherConsumer.handle, anotherConsumer.uri, ["2"])

    _verify_delivery(consumer.handle, consumer.uri, ["1", "2"])
    # not confirming

    assert (
        producer.handle.post(producer.uri, payload=["3"], block=True, wait_ack=True)
        == Client.e_SUCCESS
    )

    for anotherConsumer in other_consumers:
        _verify_delivery_and_confirm(anotherConsumer.handle, anotherConsumer.uri, ["3"])

    # consumer is over maxUnconfirmedMessages (2)
    # assert no PUSH received within 1 second
    assert not consumer.handle.outputs_regex("MESSAGE.*PUSH", timeout=1)
    msgs = consumer.handle.list(consumer.uri, block=True)
    assert len(msgs) == 2
    assert msgs[0].payload == "1"
    assert msgs[1].payload == "2"

    assert consumer.handle.confirm(consumer.uri, "*", block=True) == Client.e_SUCCESS

    # onHandleUsable kicks in
    _verify_delivery(consumer.handle, consumer.uri, ["3"])


def _verify_priority_routing(
    producers, consumers, lowPriorityConsumers, domain_urls: tc.DomainUrls
):
    uri_priority = domain_urls.uri_priority
    # Verify no messages when we start
    for consumer in consumers + lowPriorityConsumers:
        try:
            assert len(consumer.list(uri_priority, block=True)) == 0
        except RuntimeError:
            pass  # No messages, that's what we want

    # Route messages and verify
    for producer in producers:
        assert (
            producer.post(uri_priority, payload=["msg"], block=True, wait_ack=True)
            == Client.e_SUCCESS
        )

    for consumer in consumers:
        _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    for consumer in lowPriorityConsumers:
        # assert no PUSH received within 1 second
        assert not consumer.outputs_regex("MESSAGE.*PUSH", timeout=1)
        assert not consumer.list(uri_priority, block=True)


def test_open_queue(cartesian_product_cluster: Cluster, domain_urls: tc.DomainUrls):
    cluster = cartesian_product_cluster
    uri_priority = domain_urls.uri_priority
    [consumer] = cluster.open_priority_queues(
        1, flags=["read"], uri_priority=uri_priority
    )
    [producer] = cluster.open_priority_queues(
        1, flags=["write"], uri_priority=uri_priority
    )
    producer.post(payload=["foo"], succeed=True)
    consumer.client.wait_push_event()
    msgs = consumer.list(block=True)
    assert len(msgs) == 1
    assert msgs[0].payload == "foo"


def test_verify_priority(cluster: Cluster, domain_urls: tc.DomainUrls):
    uri_priority = domain_urls.uri_priority
    proxies = cluster.proxy_cycle()

    # 1: Setup producers and consumers
    # Proxy in same datacenter as leader/primary
    proxy1 = next(proxies)

    producer1 = proxy1.create_client("producer1")
    assert (
        producer1.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    consumer1 = proxy1.create_client("consumer1")
    assert (
        consumer1.open(uri_priority, flags=["read"], consumer_priority=2, block=True)
        == Client.e_SUCCESS
    )

    # Replica proxy
    proxy2 = next(proxies)

    producer2 = proxy2.create_client("producer2")
    assert (
        producer2.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    consumer2 = proxy2.create_client("consumer2")
    assert (
        consumer2.open(uri_priority, flags=["read"], consumer_priority=2, block=True)
        == Client.e_SUCCESS
    )

    consumer3 = proxy1.create_client("consumer3")
    assert (
        consumer3.open(uri_priority, flags=["read"], consumer_priority=1, block=True)
        == Client.e_SUCCESS
    )

    consumer4 = proxy2.create_client("consumer4")
    assert (
        consumer4.open(uri_priority, flags=["read"], consumer_priority=1, block=True)
        == Client.e_SUCCESS
    )

    # 2: Route messages and verify
    _verify_priority_routing(
        [producer1, producer2],
        [consumer1, consumer2],
        [consumer3, consumer4],
        domain_urls,
    )

    # 3: Close everything
    _close_clients(
        [producer1, consumer1, producer2, consumer2, consumer3, consumer4],
        [uri_priority],
    )
    _stop_clients([producer1, consumer1, producer2, consumer2, consumer3, consumer4])

    # 4: Repeat the test with reeverse order of opening clients (consumers
    #    first).
    consumer1 = proxy1.create_client("consumer1")
    assert (
        consumer1.open(uri_priority, flags=["read"], consumer_priority=2, block=True)
        == Client.e_SUCCESS
    )

    consumer2 = proxy2.create_client("consumer2")
    assert (
        consumer2.open(uri_priority, flags=["read"], consumer_priority=2, block=True)
        == Client.e_SUCCESS
    )

    consumer3 = proxy1.create_client("consumer3")
    assert (
        consumer3.open(uri_priority, flags=["read"], consumer_priority=1, block=True)
        == Client.e_SUCCESS
    )

    consumer4 = proxy2.create_client("consumer4")
    assert (
        consumer4.open(uri_priority, flags=["read"], consumer_priority=1, block=True)
        == Client.e_SUCCESS
    )

    producer2 = proxy2.create_client("producer2")
    assert (
        producer2.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    producer1 = proxy1.create_client("producer1")
    assert (
        producer1.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    # 5: Route messages and verify
    _verify_priority_routing(
        [producer1, producer2],
        [consumer1, consumer2],
        [consumer3, consumer4],
        domain_urls,
    )

    # 6: test maxUnconfirmedMessages, maxUnconfirmedBytes
    assert (
        consumer2.configure(
            uri_priority,
            consumer_priority=3,
            max_unconfirmed_messages=2,
            max_unconfirmed_bytes=3,
            block=True,
        )
        == Client.e_SUCCESS
    )

    _verify_max_messages_max_bytes_routing(
        BmqClient(producer2, uri_priority),
        BmqClient(consumer2, uri_priority),
        [],
    )

    # 7: Close everything
    _close_clients(
        [producer1, consumer1, producer2, consumer2, consumer3, consumer4],
        [uri_priority],
    )
    _stop_clients([producer1, consumer1, producer2, consumer2, consumer3, consumer4])


def test_verify_fanout(cluster: Cluster, domain_urls: tc.DomainUrls):
    du = domain_urls

    # 1: Setup producers and consumers
    proxies = cluster.proxy_cycle()

    # Proxy in same datacenter as leader/primary
    proxy1 = next(proxies)

    fooConsumerAndProducerOnPrimaryProxy = proxy1.create_client(
        "fooConsumerAndProducerOnPrimaryProxy"
    )

    # testing {client1 open "foo" for read, client2 open "bar" for read,
    #          client1 open for write} sequence.

    assert (
        fooConsumerAndProducerOnPrimaryProxy.open(
            du.uri_fanout_foo, flags=["read"], block=True
        )
        == Client.e_SUCCESS
    )

    barConsumerOnPrimaryProxy = proxy1.create_client("barConsumerOnPrimaryProxy")
    assert (
        barConsumerOnPrimaryProxy.open(du.uri_fanout_bar, flags=["read"], block=True)
        == Client.e_SUCCESS
    )

    assert (
        fooConsumerAndProducerOnPrimaryProxy.open(
            du.uri_fanout, flags=["write", "ack"], block=True
        )
        == Client.e_SUCCESS
    )

    assert (
        barConsumerOnPrimaryProxy.close(du.uri_fanout_bar, block=True)
        == Client.e_SUCCESS
    )

    # Replica proxy
    proxy2 = next(proxies)

    producerOnReplicaProxy = proxy2.create_client("producerOnReplicaProxy")
    assert (
        producerOnReplicaProxy.open(du.uri_fanout, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    barConsumerOnReplicaProxy = proxy2.create_client("barConsumerOnReplicaProxy")
    assert (
        barConsumerOnReplicaProxy.open(du.uri_fanout_bar, flags=["read"], block=True)
        == Client.e_SUCCESS
    )

    assert (
        len(fooConsumerAndProducerOnPrimaryProxy.list(du.uri_fanout_foo, block=True))
        == 0
    )
    assert len(barConsumerOnReplicaProxy.list(du.uri_fanout_bar, block=True)) == 0

    # 2: Route messages and verify
    assert (
        fooConsumerAndProducerOnPrimaryProxy.post(
            du.uri_fanout, payload=["msg1"], block=True, wait_ack=True
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(
        fooConsumerAndProducerOnPrimaryProxy, du.uri_fanout_foo, ["msg1"]
    )

    _verify_delivery_and_confirm(barConsumerOnReplicaProxy, du.uri_fanout_bar, ["msg1"])

    assert (
        producerOnReplicaProxy.post(
            du.uri_fanout, payload=["msg2"], block=True, wait_ack=True
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(
        fooConsumerAndProducerOnPrimaryProxy, du.uri_fanout_foo, ["msg2"]
    )

    _verify_delivery_and_confirm(barConsumerOnReplicaProxy, du.uri_fanout_bar, ["msg2"])

    # 3: test maxUnconfirmedMessages, maxUnconfirmedBytes
    assert (
        barConsumerOnReplicaProxy.configure(
            du.uri_fanout_bar,
            max_unconfirmed_messages=2,
            max_unconfirmed_bytes=3,
            block=True,
        )
        == Client.e_SUCCESS
    )

    _verify_max_messages_max_bytes_routing(
        BmqClient(handle=producerOnReplicaProxy, uri=du.uri_fanout),
        BmqClient(handle=barConsumerOnReplicaProxy, uri=du.uri_fanout_bar),
        [BmqClient(handle=fooConsumerAndProducerOnPrimaryProxy, uri=du.uri_fanout_foo)],
    )

    # 4: Close everything
    _close_clients(
        [
            fooConsumerAndProducerOnPrimaryProxy,
            fooConsumerAndProducerOnPrimaryProxy,
            producerOnReplicaProxy,
            barConsumerOnReplicaProxy,
        ],
        [du.uri_fanout, du.uri_fanout_foo, du.uri_fanout, du.uri_fanout_bar],
    )

    _stop_clients(
        [
            fooConsumerAndProducerOnPrimaryProxy,
            producerOnReplicaProxy,
            barConsumerOnReplicaProxy,
        ]
    )


def test_verify_broadcast(
    cluster: Cluster,
    domain_urls: tc.DomainUrls,  # pylint: disable=unused-argument
):
    # 1: Setup producers and consumers
    proxies = cluster.proxy_cycle()

    # Proxy in same datacenter as leader/primary
    proxy1 = next(proxies)

    producer1 = proxy1.create_client("producer1")
    assert (
        producer1.open(tc.URI_BROADCAST, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    consumer1 = proxy1.create_client("consumer1")
    assert (
        consumer1.open(tc.URI_BROADCAST, flags=["read"], block=True) == Client.e_SUCCESS
    )

    # Replica proxy
    proxy2 = next(proxies)

    producer2 = proxy2.create_client("producer2")
    assert (
        producer2.open(tc.URI_BROADCAST, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    consumer2 = proxy2.create_client("consumer2")
    assert (
        consumer2.open(tc.URI_BROADCAST, flags=["read"], block=True) == Client.e_SUCCESS
    )

    assert len(consumer1.list(tc.URI_BROADCAST, block=True)) == 0
    assert len(consumer2.list(tc.URI_BROADCAST, block=True)) == 0

    # 2: Route messages and verify
    assert (
        producer1.post(tc.URI_BROADCAST, payload=["msg1"], block=True, wait_ack=True)
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer1, tc.URI_BROADCAST, ["msg1"])

    _verify_delivery_and_confirm(consumer2, tc.URI_BROADCAST, ["msg1"])

    assert (
        producer2.post(tc.URI_BROADCAST, payload=["msg2"], block=True, wait_ack=True)
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer1, tc.URI_BROADCAST, ["msg2"])

    _verify_delivery_and_confirm(consumer2, tc.URI_BROADCAST, ["msg2"])

    # 4: Close everything
    _close_clients([producer1, consumer1, producer2, consumer2], [tc.URI_BROADCAST])

    _stop_clients([producer1, consumer1, producer2, consumer2])


def test_verify_redelivery(cluster: Cluster, domain_urls: tc.DomainUrls):
    """Drop one consumer having unconfirmed message while there is another
    consumer unable to take the message (due to max_unconfirmed_messages
    limit).  Then start new consumer and make sure it does not crash and
    receives that unconfirmed message.
    """
    du = domain_urls
    proxies = cluster.proxy_cycle()

    # Proxy in same datacenter as leader/primary
    proxy = next(proxies)

    producer = proxy.create_client("producer1")
    producer.open(du.uri_fanout, flags=["write", "ack"], succeed=True)

    consumer1 = proxy.create_client("consumer1")
    consumer1.open(
        du.uri_fanout_foo,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )

    consumer2 = proxy.create_client("consumer2")
    consumer2.open(
        du.uri_fanout_foo,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )

    producer.post(du.uri_fanout, payload=["1"], succeed=True, wait_ack=True)
    producer.post(du.uri_fanout, payload=["2"], succeed=True, wait_ack=True)

    consumer1.wait_push_event()
    before = consumer1.list(du.uri_fanout_foo, block=True)

    assert len(before) == 1

    consumer2.wait_push_event()

    consumer1.stop_session(block=True)

    consumer1 = proxy.create_client("consumer1")
    consumer1.open(
        du.uri_fanout_foo,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )

    consumer1.wait_push_event()
    after = consumer1.list(du.uri_fanout_foo, block=True)

    assert len(after) == 1

    assert before[0].payload == after[0].payload

    _stop_clients([producer, consumer1, consumer2])


def test_verify_priority_queue_redelivery(cluster: Cluster, domain_urls: tc.DomainUrls):
    """Restart consumer having unconfirmed messages while a producer is
    still present (queue context is not erased).  Make sure the consumer
    receives the unconfirmed messages.
    """
    uri_priority = domain_urls.uri_priority
    proxies = cluster.proxy_cycle()

    # Proxy in same datacenter as leader/primary
    proxy = next(proxies)

    producer = proxy.create_client("producer")
    producer.open(uri_priority, flags=["write", "ack"], succeed=True)

    consumer = proxy.create_client("consumer")
    consumer.open(
        uri_priority,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )

    producer.post(uri_priority, payload=["1"], succeed=True, wait_ack=True)
    producer.post(uri_priority, payload=["2"], succeed=True, wait_ack=True)

    consumer.wait_push_event()
    before = consumer.list(uri_priority, block=True)

    consumer.stop_session(block=True)

    consumer = proxy.create_client("consumer")
    consumer.open(
        uri_priority,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )

    consumer.wait_push_event()
    after = consumer.list(uri_priority, block=True)

    assert before == after

    _stop_clients([producer, consumer])


def test_verify_partial_close(multi_node: Cluster, domain_urls: tc.DomainUrls):
    """Drop one of two producers both having unacked message (primary is
    suspended.  Make sure the remaining producer does not get NACK but gets
    ACK when primary resumes.
    """
    uri_fanout = domain_urls.uri_fanout
    proxies = multi_node.proxy_cycle()

    proxy = next(proxies)
    proxy = next(proxies)

    producer1 = proxy.create_client("producer1")
    producer1.open(uri_fanout, flags=["write", "ack"], succeed=True)

    producer2 = proxy.create_client("producer2")
    producer2.open(uri_fanout, flags=["write", "ack"], succeed=True)

    leader = multi_node.last_known_leader
    leader.suspend()

    producer1.post(uri_fanout, payload=["1"], succeed=True, wait_ack=False)
    producer2.post(uri_fanout, payload=["2"], succeed=True, wait_ack=False)

    producer2.stop_session(block=True)

    leader.resume()

    producer1.capture(r"ACK #0: \[ type = ACK status = SUCCESS", 2)

    _stop_clients([producer1, producer2])


def test_multi_interface_connect(multi_interface: Cluster, domain_urls: tc.DomainUrls):
    """Simple test to connect to a cluster with multiple ports listening."""
    uri_priority = domain_urls.uri_priority
    cluster = multi_interface
    brokers = cluster.nodes() + cluster.proxies()
    for broker in brokers:
        for i, listener in enumerate(broker.config.listeners):
            port = listener.port
            producer = broker.create_client(f"producer{i}", port=port)
            consumer = broker.create_client(f"consumer{i}", port=port)
            producer.open(uri_priority, flags=["write", "ack"], succeed=True)
            consumer.open(
                uri_priority,
                flags=["read"],
                consumer_priority=1,
                max_unconfirmed_messages=1,
                succeed=True,
            )
            producer.post(uri_priority, payload=[f"{i}"], succeed=True, wait_ack=True)
            assert consumer.wait_push_event()
            msgs = consumer.list(block=True)
            assert len(msgs) == 1
            assert msgs[0].payload == f"{i}"
            consumer.confirm(uri_priority, msgs[0].guid, succeed=True)
            _stop_clients([producer, consumer])


def test_multi_interface_share_queues(
    multi_interface: Cluster, domain_urls: tc.DomainUrls
):
    """Check that clients connecting on different ports still work together."""
    uri_priority = domain_urls.uri_priority
    cluster = multi_interface
    broker = next(cluster.proxy_cycle())
    [listener1, listener2] = broker.config.listeners
    producer = broker.create_client("producer", port=listener1.port)
    consumer = broker.create_client("consumer", port=listener2.port)
    producer.open(uri_priority, flags=["write", "ack"], succeed=True)
    consumer.open(
        uri_priority,
        flags=["read"],
        consumer_priority=1,
        max_unconfirmed_messages=1,
        succeed=True,
    )
    producer.post(uri_priority, payload=["foo"], succeed=True, wait_ack=True)
    assert consumer.wait_push_event()
    msgs = consumer.list(block=True)
    assert len(msgs) == 1
    assert msgs[0].payload == "foo"
    consumer.confirm(uri_priority, msgs[0].guid, succeed=True)
    _stop_clients([producer, consumer])


@start_cluster(True, True, True)
@tweak.cluster.queue_operations.open_timeout_ms(2)
def test_command_timeout(multi_node: Cluster, domain_urls: tc.DomainUrls):
    """Simple test to execute onOpenQueueResponse timeout."""

    du = domain_urls

    # make sure the cluster is healthy and the queue is assigned
    # Cannot use proxies as they do not read cluster config

    leader = multi_node.last_known_leader
    host = multi_node.nodes()[0]
    if host == leader:
        host = multi_node.nodes()[1]

    client = host.create_client("client")
    # this may fail due to the short timeout; we just need queue assigned
    client.open(du.uri_fanout, flags=["write", "ack"], block=True)

    leader.suspend()

    result = client.open(du.uri_fanout_foo, flags=["read"], block=True)
    leader.resume()

    assert result == Client.e_TIMEOUT


def test_queue_purge_command(multi_node: Cluster, domain_urls: tc.DomainUrls):
    """Ensure that 'queue purge' command is working as expected.  Post a
    message to the queue, then purge the queue, then bring up a consumer.
    Ensure that consumer does not receive any message.
    """
    du = domain_urls
    proxy = next(multi_node.proxy_cycle())

    # Start a producer and post a message
    producer = proxy.create_client("producer")
    producer.open(du.uri_fanout, flags=["write", "ack"], succeed=True)
    producer.post(du.uri_fanout, ["msg1"], succeed=True, wait_ack=True)

    leader = multi_node.last_known_leader

    # Purge queue, but *only* for 'foo' appId
    leader.command(f"DOMAINS DOMAIN {du.domain_fanout} QUEUE {tc.TEST_QUEUE} PURGE foo")

    # Open consumers for all appIds and ensure that the one with 'foo' appId
    # does not receive the message, while other consumers do.
    consumer1 = proxy.create_client("consumer1")
    consumer1.open(du.uri_fanout_foo, flags=["read"], succeed=True)

    consumer2 = proxy.create_client("consumer2")
    consumer2.open(du.uri_fanout_bar, flags=["read"], succeed=True)

    consumer3 = proxy.create_client("consumer3")
    consumer3.open(du.uri_fanout_baz, flags=["read"], succeed=True)

    assert consumer2.wait_push_event()
    msgs = consumer2.list(block=True)
    assert len(msgs) == 1
    assert msgs[0].payload == "msg1"

    assert consumer3.wait_push_event()
    msgs = consumer3.list(block=True)
    assert len(msgs) == 1
    assert msgs[0].payload == "msg1"

    assert not consumer1.wait_push_event(timeout=5, quiet=True)
    msgs = consumer1.list(block=True)
    assert len(msgs) == 0

    consumer2.confirm(du.uri_fanout_bar, "*", succeed=True)
    consumer3.confirm(du.uri_fanout_baz, "*", succeed=True)

    # Stop all consumers, post another message, then purge entire queue
    # (i.e., all appIds), then restart all consumers and ensure that none
    # of them got any messages.
    consumer1.close(du.uri_fanout_foo, succeed=True)
    consumer2.close(du.uri_fanout_bar, succeed=True)
    consumer3.close(du.uri_fanout_baz, succeed=True)

    producer.post(du.uri_fanout, ["msg2"], succeed=True, wait_ack=True)

    leader.command(f"DOMAINS DOMAIN {du.domain_fanout} QUEUE {tc.TEST_QUEUE} PURGE *")

    consumer1 = proxy.create_client("consumer1")
    consumer1.open(du.uri_fanout_foo, flags=["read"], succeed=True)
    consumer2 = proxy.create_client("consumer2")
    consumer2.open(du.uri_fanout_bar, flags=["read"], succeed=True)
    consumer3 = proxy.create_client("consumer3")
    consumer3.open(du.uri_fanout_baz, flags=["read"], succeed=True)

    consumers = [consumer1, consumer2, consumer3]

    for consumer in consumers:
        assert not consumer.wait_push_event(timeout=2, quiet=True)
        msgs = consumer.list(block=True)
        assert len(msgs) == 0


def test_message_properties(cluster: Cluster, domain_urls: tc.DomainUrls):
    """Ensure that posting different sequences of MessageProperties works."""
    uri_priority = domain_urls.uri_priority
    proxies = cluster.proxy_cycle()

    # 1: Setup producers and consumers
    # Proxy in same datacenter as leader/primary
    proxy1 = next(proxies)

    producer1 = proxy1.create_client("producer1")
    assert (
        producer1.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    consumer = proxy1.create_client("consumer")
    assert consumer.open(uri_priority, flags=["read"], block=True) == Client.e_SUCCESS

    # Replica proxy
    proxy2 = next(proxies)

    producer2 = proxy2.create_client("producer2")
    assert (
        producer2.open(uri_priority, flags=["write", "ack"], block=True)
        == Client.e_SUCCESS
    )

    # 2: Route messages and verify

    assert (
        producer1.post(
            uri_priority,
            payload=["msg"],
            block=True,
            wait_ack=True,
            messageProperties=[],
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    assert (
        producer1.post(
            uri_priority,
            payload=["msg"],
            block=True,
            wait_ack=True,
            messageProperties=[
                {"name": "pairs_", "value": "3", "type": "E_INT"},
                {"name": "p1", "value": "1", "type": "E_INT"},
                {"name": "p1_value", "value": "1", "type": "E_INT"},
                {"name": "p3", "value": "1", "type": "E_INT"},
                {"name": "p3_value", "value": "1", "type": "E_INT"},
                {"name": "p4", "value": "1", "type": "E_STRING"},
                {"name": "p4_value", "value": "1", "type": "E_STRING"},
            ],
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    assert (
        producer1.post(
            uri_priority,
            payload=["msg"],
            block=True,
            wait_ack=True,
            messageProperties=[
                {"name": "pairs_", "value": "4", "type": "E_INT"},
                {"name": "p1", "value": "1", "type": "E_INT"},
                {"name": "p1_value", "value": "1", "type": "E_INT"},
                {"name": "p2", "value": "1", "type": "E_STRING"},
                {"name": "p2_value", "value": "1", "type": "E_STRING"},
                {"name": "p3", "value": "1", "type": "E_INT"},
                {"name": "p3_value", "value": "1", "type": "E_INT"},
                {"name": "p4", "value": "1", "type": "E_STRING"},
                {"name": "p4_value", "value": "1", "type": "E_STRING"},
            ],
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    assert (
        producer1.post(
            uri_priority,
            payload=["msg"],
            block=True,
            wait_ack=True,
            messageProperties=[
                {"name": "pairs_", "value": "3", "type": "E_INT"},
                {"name": "p1", "value": "1", "type": "E_INT"},
                {"name": "p1_value", "value": "1", "type": "E_INT"},
                {"name": "p3", "value": "1", "type": "E_INT"},
                {"name": "p3_value", "value": "1", "type": "E_INT"},
                {"name": "p4", "value": "1", "type": "E_STRING"},
                {"name": "p4_value", "value": "1", "type": "E_STRING"},
            ],
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    assert (
        producer1.post(
            uri_priority,
            payload=["msg"],
            block=True,
            wait_ack=True,
            messageProperties=[
                {"name": "pairs_", "value": "4", "type": "E_INT"},
                {"name": "p1", "value": "1", "type": "E_INT"},
                {"name": "p1_value", "value": "1", "type": "E_INT"},
                {"name": "p2", "value": "1", "type": "E_STRING"},
                {"name": "p2_value", "value": "1", "type": "E_STRING"},
                {"name": "p3", "value": "1", "type": "E_INT"},
                {"name": "p3_value", "value": "1", "type": "E_INT"},
                {"name": "p4", "value": "1", "type": "E_STRING"},
                {"name": "p4_value", "value": "1", "type": "E_STRING"},
            ],
        )
        == Client.e_SUCCESS
    )

    _verify_delivery_and_confirm(consumer, uri_priority, ["msg"])

    # 3: Close everything
    _close_clients(
        [producer1, consumer, producer2],
        [uri_priority],
    )
    _stop_clients([producer1, consumer, producer2])
