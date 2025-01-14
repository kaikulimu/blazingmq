# Copyright 2025 Bloomberg Finance L.P.
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
Testing rollover of CSL file.
"""
import blazingmq.dev.it.testconstants as tc
from blazingmq.dev.it.fixtures import (  # pylint: disable=unused-import
    Cluster,
    cluster,
    order,
    tweak,
)
import time

pytestmark = order(999) # TODO

timeout = 15 # TODO 60


class TestRolloverCSL:
    @tweak.cluster.partition_config.max_cslfile_size(2000) # TODO
    @tweak.cluster.queue_operations.keepalive_duration_ms(1) # TODO
    def test_TODO(self, cluster: Cluster):
        leader = cluster.last_known_leader
        proxy = next(cluster.proxy_cycle())
        self.writer = proxy.create_client("writers")

        for i in range(0, 3):
            self.writer.open(f"bmq://{tc.DOMAIN_PRIORITY_SC}/q{i}", flags=["write,ack"], succeed=True)
            self.writer.close(f"bmq://{tc.DOMAIN_PRIORITY_SC}/q{i}", succeed=True)
        self.writer.open(f"bmq://{tc.DOMAIN_FANOUT_SC}/q0", flags=["write,ack"], succeed=True)
        assert leader.outputs_regex(r"ueueUn", timeout)

        # Assigning these two queues will cause rollover
        self.writer.open(f"bmq://{tc.DOMAIN_PRIORITY_SC}/q_last", flags=["write,ack"], succeed=True)
        self.writer.open(f"bmq://{tc.DOMAIN_PRIORITY_SC}/q_last_2", flags=["write,ack"], succeed=True)

        assert leader.outputs_regex(r"Rolling over from log with logId", timeout)

        cluster.restart_nodes()
        # For a standard cluster, states have already been restored as part of
        # leader re-election.
        if cluster.is_single_node:
            self.writer.wait_state_restored()

        self.reader = proxy.create_client("readers")
        self.reader.open(f"bmq://{tc.DOMAIN_FANOUT_SC}/q0?id=foo", flags=["read"], succeed=True)
        self.reader.open(f"bmq://{tc.DOMAIN_FANOUT_SC}/q0?id=bar", flags=["read"], succeed=True)
        self.reader.open(f"bmq://{tc.DOMAIN_FANOUT_SC}/q0?id=baz", flags=["read"], succeed=True)



