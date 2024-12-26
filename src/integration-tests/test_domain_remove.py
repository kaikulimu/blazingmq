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
This suite of test cases verifies the admin command
"DOMAINS REMOVE <domain> [finalize]" work as expected
"""

import blazingmq.dev.it.testconstants as tc
from blazingmq.dev.it.fixtures import (
    multi_node,
    single_node,
    cluster,
    Cluster,
)
from blazingmq.dev.it.process.admin import AdminClient
from blazingmq.dev.it.process.client import Client
import time


def test_remove_domain_with_queue_close(cluster: Cluster):
    proxies = cluster.proxy_cycle()
    proxy = next(proxies)

    # producer and consumer open the queue,
    # post and confirm messages and both close
    producer = proxy.create_client("producer")
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)

    consumer = proxy.create_client("consumer")
    consumer.open(tc.URI_PRIORITY, flags=["read"], succeed=True)

    producer.post(
        tc.URI_PRIORITY,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    consumer.confirm(tc.URI_PRIORITY, "*", succeed=True)
    producer.close(tc.URI_PRIORITY, succeed=True)
    consumer.close(tc.URI_PRIORITY, succeed=True)

    # send remove domain admin command
    # command couldn't go through since there's a queue open
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "while there are queues open" not in res


def test_remove_domain_when_cluster_unhealthy(multi_node: Cluster):
    proxies = multi_node.proxy_cycle()
    proxy = next(proxies)

    # find the two nodes which are not the known leader
    leader = multi_node.last_known_leader
    replicas = multi_node.nodes(exclude=leader)
    member = replicas[0]

    def write_messages(uri):
        # producer send a message, client confirm, then both close connection
        producer = proxy.create_client("producer")
        producer.open(uri, flags=["write"], succeed=True)

        consumer = proxy.create_client("consumer")
        consumer.open(uri, flags=["read"], succeed=True)

        producer.post(uri, [f"msg{i}" for i in range(5)], succeed=True, wait_ack=True)

        consumer.confirm(uri, "+1", succeed=True)

        producer.close(uri, succeed=True)
        consumer.close(uri, succeed=True)

    write_messages(tc.URI_PRIORITY)

    # set quorum to make it impossible to select a leader
    for node in multi_node.nodes():
        node.set_quorum(99, succeed=True)

    # kill the leader to make the cluster unhealthy
    leader.check_exit_code = False
    leader.kill()
    leader.wait()

    # send remove domain admin command
    # command couldn't go through since state is unhealthy
    admin = AdminClient()
    admin.connect(member.config.host, int(member.config.port))
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "Error occurred routing command to this node" in res
    assert res.split("\n").count("No queue purged.") == 3

    # restart the previous leader node
    # set quorum to make a member become the leader
    # wait until the cluster become healthy again
    leader.start()
    leader.wait()
    replicas[1].set_quorum(1)
    leader.wait_status(wait_leader=True, wait_ready=False)

    # send DOMAINS REMOVE admin command again
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "Purged 4 message(s) for a total of 16  B from 1 queue(s):" in res
    assert res.split("\n").count("No queue purged.") == 3


def test_remove_different_domain(cluster: Cluster):
    proxies = cluster.proxy_cycle()

    # producer produces messages and then closes connection
    producer = next(proxies).create_client("producer")
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)

    producer.post(
        tc.URI_PRIORITY,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    producer.close(tc.URI_PRIORITY)

    # send remove domain admin command
    # for a different domain
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))

    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY_SC}")
    assert "No queue purged." in res

    # do the same things for a different pair reversely
    producer.open(tc.URI_FANOUT_SC, flags=["write"], succeed=True)

    producer.post(
        tc.URI_FANOUT_SC,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    producer.close(tc.URI_FANOUT_SC)

    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_FANOUT}")
    assert "No queue purged." in res


def test_open_queue_after_remove_domain(cluster: Cluster):
    proxies = cluster.proxy_cycle()
    next(proxies)  # eastp
    proxy = next(proxies)  # westp

    # producer produces messages and consumer confirms
    # then both close connections
    producer = proxy.create_client("producer")
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)

    consumer = proxy.create_client("consumer")
    consumer.open(tc.URI_PRIORITY, flags=["read"], succeed=True)

    producer.post(
        tc.URI_PRIORITY,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    consumer.confirm(tc.URI_PRIORITY, "*", succeed=True)
    producer.close(tc.URI_PRIORITY, succeed=True)
    consumer.close(tc.URI_PRIORITY, succeed=True)

    # send remove domain admin command
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")

    # open queues on the removed domain should fail
    assert producer.open(tc.URI_PRIORITY, flags=["write"], block=True) < 0


def test_remove_domain_with_queue_open(cluster: Cluster):
    proxies = cluster.proxy_cycle()
    proxy = next(proxies)

    # producer produces messages and consumer confirms
    # then both close connections
    producer = proxy.create_client("producer")
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)

    consumer = proxy.create_client("consumer")
    consumer.open(tc.URI_PRIORITY, flags=["read"], succeed=True)

    producer.post(
        tc.URI_PRIORITY,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    consumer.confirm(tc.URI_PRIORITY, "*", succeed=True)

    # send admin command
    # when both producer and consumer open
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert (
        f"Trying to remove the domain '{tc.DOMAIN_PRIORITY}' while there are queues open"
        in res
    )

    # close producer and send the command again
    producer.close(tc.URI_PRIORITY, succeed=True)
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert (
        f"Trying to remove the domain '{tc.DOMAIN_PRIORITY}' while there are queues open"
        in res
    )

    # open producer and close consumer and send the command again
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)
    consumer.close(tc.URI_PRIORITY, succeed=True)
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert (
        f"Trying to remove the domain '{tc.DOMAIN_PRIORITY}' while there are queues open"
        in res
    )

    # close both and send the command again
    producer.close(tc.URI_PRIORITY, succeed=True)
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "while there are queues open" not in res


def test_remove_domain_with_unconfirmed_message(cluster: Cluster):
    proxies = cluster.proxy_cycle()
    proxy = next(proxies)

    # producer open the queue,
    # produce messages and close the queue
    producer = proxy.create_client("producer")
    producer.open(tc.URI_PRIORITY, flags=["write"], succeed=True)

    producer.post(
        tc.URI_PRIORITY,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    producer.close(tc.URI_PRIORITY, succeed=True)

    # send admin command
    # unconfirmed messages will be purged
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "Purged 3 message(s)" in res


def test_remove_domain_not_on_disk(cluster: Cluster):
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    domain_name = "domain.foo"
    res = admin.send_admin(f"DOMAINS REMOVE {domain_name}")
    assert f"Domain '{domain_name}' doesn't exist" in res


def test_remove_domain_on_disk_not_in_cache(cluster: Cluster):
    admin = AdminClient()
    leader = cluster.last_known_leader
    admin.connect(leader.config.host, int(leader.config.port))
    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_BROADCAST}")
    assert "Trying to remove a nonexistent domain" not in res


def test_send_to_replicas(multi_node: Cluster):
    proxies = multi_node.proxy_cycle()
    proxy = next(proxies)

    queue1 = f"bmq://{tc.DOMAIN_PRIORITY}/q1"
    queue2 = f"bmq://{tc.DOMAIN_PRIORITY}/q2"

    # producer and consumer open the queue,
    # post and confirm messages and both close
    producer = proxy.create_client("producer")
    producer.open(queue1, flags=["write"], succeed=True)

    consumer = proxy.create_client("consumer")
    consumer.open(queue1, flags=["read"], succeed=True)

    producer.post(
        queue1,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    consumer.confirm(queue1, "*", succeed=True)
    producer.close(queue1, succeed=True)
    consumer.close(queue1, succeed=True)

    # producer open another queue, should be on a different partition
    producer.open(queue2, flags=["write"], succeed=True)
    producer.post(
        queue2,
        [f"msg{i}" for i in range(3)],
        succeed=True,
        wait_ack=True,
    )
    producer.close(queue2, succeed=True)

    leader = multi_node.last_known_leader
    member = multi_node.nodes(exclude=leader)[0]

    # send remove domain admin command
    # command couldn't go through since there's a queue open
    admin = AdminClient()
    admin.connect(member.config.host, int(member.config.port))

    res = admin.send_admin(f"DOMAINS REMOVE {tc.DOMAIN_PRIORITY}")
    assert "Purged" in res
