# Copyright contributors to the ITBench project. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import shutil
import traceback
from typing import Literal, TypedDict

import yaml
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from ciso_agent.agents.kubernetes_kubectl_opa import KubernetesKubectlOPACrew
from ciso_agent.agents.kubernetes_kyverno import KubernetesKyvernoCrew
from ciso_agent.agents.rhel_playbook_opa import RHELPlaybookOPACrew
from ciso_agent.llm import call_llm, extract_code

load_dotenv()

kubernetes_kyverno_crew = KubernetesKyvernoCrew()
kubernetes_kubectl_opa_crew = KubernetesKubectlOPACrew()
rhel_playbook_opa_crew = RHELPlaybookOPACrew()


sub_agent_descs = {
    "kubernetes_kyverno": {
        "goal": kubernetes_kyverno_crew.agent_goal,
        "tool": kubernetes_kyverno_crew.tool_description,
        "input": kubernetes_kyverno_crew.input_description,
        "output": kubernetes_kyverno_crew.output_description,
    },
    "kubernetes_kubectl_opa": {
        "goal": kubernetes_kubectl_opa_crew.agent_goal,
        "tool": kubernetes_kubectl_opa_crew.tool_description,
        "input": kubernetes_kubectl_opa_crew.input_description,
        "output": kubernetes_kubectl_opa_crew.output_description,
    },
    "rhel_playbook_opa": {
        "goal": rhel_playbook_opa_crew.agent_goal,
        "tool": rhel_playbook_opa_crew.tool_description,
        "input": rhel_playbook_opa_crew.input_description,
        "output": rhel_playbook_opa_crew.output_description,
    },
}


class CISOState(TypedDict):
    # input params
    goal: str
    kubeconfig: str
    ansible_inventory: str
    workdir: str

    # set by task_selector node
    action_sequence: list = []
    task_index: int = 0
    route: str

    # set by Crew agent
    result: dict = {}

    # set by summary node
    summary: str


class Action(TypedDict):
    description: str
    node: str
    input: dict = {}
    output: dict = {}


# TODO: add eval_policy
class CISOManager:
    def __init__(self, eval_policy: bool = False):
        workflow = StateGraph(CISOState)

        workflow.add_node("task_selector", self.task_selector)
        workflow.add_node("task_handler", self.task_handler)
        workflow.add_node("kubernetes_kyverno", kubernetes_kyverno_crew.kickoff)
        workflow.add_node("kubernetes_kubectl_opa", kubernetes_kubectl_opa_crew.kickoff)
        workflow.add_node("rhel_playbook_opa", rhel_playbook_opa_crew.kickoff)
        workflow.add_node("reporter", self.reporter)

        workflow.set_entry_point("task_selector")
        workflow.add_edge("task_selector", "task_handler")
        workflow.add_conditional_edges(
            "task_handler",
            self.switch_routes,
        )
        workflow.add_edge("kubernetes_kyverno", "task_handler")
        workflow.add_edge("kubernetes_kubectl_opa", "task_handler")
        workflow.add_edge("rhel_playbook_opa", "task_handler")
        workflow.add_edge("reporter", END)

        self.app = workflow.compile()

    def invoke(self, state: CISOState):
        print("\033[36m" + "=" * 90 + "\033[0m")
        print("\033[36m # Goal:\033[0m")
        print("\033[36m" + "=" * 90 + "\033[0m")
        print("\033[36m" + state["goal"] + "\033[0m")
        print("")
        state["action_sequence"] = []
        state["task_index"] = 0
        state["route"] = ""
        state["result"] = {}
        output = self.app.invoke(state)
        o_str = json.dumps(output)
        o_dict = json.loads(o_str)
        print("\033[36m" + "=" * 90 + "\033[0m")
        print("\033[36m # Result:\033[0m")
        print("\033[36m" + "=" * 90 + "\033[0m")
        print("")
        print("\033[36m" + yaml.safe_dump(o_dict["result"], sort_keys=False, width=1024) + "\033[0m")
        return o_dict

    def save_graph(self):
        png_graph = self.app.get_graph().draw_mermaid_png()
        fpath = "graph.png"
        with open(fpath, "wb") as f:
            f.write(png_graph)

    def task_selector(self, state: CISOState):
        goal = state["goal"]

        manager_model = os.getenv("MANAGER_AGENT_MODEL_NAME", "gpt-4o-mini")
        manager_api_key = os.getenv("MANAGER_AGENT_API_KEY")
        manager_api_url = os.getenv("MANAGER_AGENT_API_URL")
        summary_prompt = f"""Extract some required information from the following goal.
Please return a parsable JSON string.
If some info is not provided, set empty string to it.

Goal:
{goal}

Expected Output:
```json
{{
    "kubeconfig": "if the path to kubeconfig is provided, set it to this",
    "ansible_inventory": "if the path to Ansible inventory file is provided, set it to this",
    "workdir": "if the path to workdir is provided, set it to this"
}}
```
"""
        answer = call_llm(
            prompt=summary_prompt,
            model=manager_model,
            api_key=manager_api_key,
            api_url=manager_api_url,
        )
        if "```" in answer:
            answer = extract_code(answer, code_type="json")
        data = json.loads(answer)
        kubeconfig = data.get("kubeconfig")
        ansible_inventory = data.get("ansible_inventory")
        workdir = data.get("workdir")
        if workdir and not os.path.exists(workdir):
            os.makedirs(workdir, exist_ok=True)

        kubecfg_path = kubeconfig
        if kubeconfig and workdir:
            kubecfg_path = os.path.join(workdir, "kubeconfig.yaml")
            if kubeconfig != kubecfg_path:
                shutil.copyfile(kubeconfig, kubecfg_path)

        inventory_path = ansible_inventory
        if ansible_inventory and workdir:
            inventory_path = os.path.join(workdir, "inventory.ansible.ini")
            if ansible_inventory != inventory_path:
                shutil.copyfile(ansible_inventory, inventory_path)

        # Task Selection
        agent_task = None
        goal_lower = goal.lower()
        if "kyverno" in goal_lower:
            agent_task = Action(
                description="kubernetes_kyverno",
                node="kubernetes_kyverno",
            )
        elif "kubectl" in goal_lower and "opa" in goal_lower:
            agent_task = Action(
                description="kubernetes_kubectl_opa",
                node="kubernetes_kubectl_opa",
            )
        elif "rhel" in goal_lower and "playbook" in goal_lower:
            agent_task = Action(
                description="rhel_playbook_opa",
                node="rhel_playbook_opa",
            )
        else:
            raise ValueError(f"failed to find an appropriate agent for this task goal: {goal}")
        reporter_task = Action(
            description="reporter",
            node="reporter",
        )
        action_sequence = [
            agent_task,
            reporter_task,
        ]
        print("Task Selection Result:", agent_task.get("node"))

        return {
            "kubeconfig": kubecfg_path,
            "ansible_inventory": inventory_path,
            "workdir": workdir,
            "action_sequence": action_sequence,
        }

    def task_handler(self, state: CISOState):
        task_index = state["task_index"]
        action_sequence = state["action_sequence"]
        route = None
        for i, action in enumerate(action_sequence):
            if i == task_index:
                node = action["node"]
                route = node.split(".")[-1]
        next_index = task_index + 1
        return {"route": route, "task_index": next_index}

    def switch_routes(self, state: CISOState) -> Literal["kubernetes_kyverno", "kubernetes_kubectl_opa", "rhel_playbook_opa", "reporter"]:
        route = state["route"]
        crew_nodes = [
            "kubernetes_kyverno",
            "kubernetes_kubectl_opa",
            "rhel_playbook_opa",
            "reporter",
        ]
        if route and route in crew_nodes:
            return route
        return "reporter"

    def reporter(self, state: CISOState):
        # add workdir prefix first
        result = state["result"]
        
        workdir = state.get("workdir")
        if isinstance(result, dict) and workdir:
            for key, val in result.items():
                if val and key.startswith("path_to_") and "/" not in val:
                    result[key] = os.path.join(workdir, val)

        # save graph.png to use it in the report.md
        self.save_graph()

        policy_path_1 = os.path.join(workdir, "policy.yaml")
        policy_path_2 = os.path.join(workdir, "policy.rego")
        policy_block = ""
        if os.path.exists(policy_path_1):
            policy = ""
            with open(policy_path_1, "r") as f:
                policy = f.read()
            policy_block = f"""
Generated Policy:
```yaml
{policy}
```

"""
        elif os.path.exists(policy_path_2):
            policy = ""
            with open(policy_path_2, "r") as f:
                policy = f.read()
            policy_block = f"""
Generated Policy:
```rego
{policy}
```

"""

        manager_model = os.getenv("MANAGER_AGENT_MODEL_NAME", "gpt-4o-mini")
        manager_api_key = os.getenv("MANAGER_AGENT_API_KEY")
        manager_api_url = os.getenv("MANAGER_AGENT_API_URL")

        goal = state["goal"]

        prompt = f"""Make an output JSON string based on the goal and the results.
Goal: {goal}

Result:
{result}

Output Format:
```json
{{
    "path_to_<FILE_DESCRIPTION>": <PLACEHOLDER>,
}}
```
"""
        answer = call_llm(
            prompt=prompt,
            model=manager_model,
            api_key=manager_api_key,
            api_url=manager_api_url,
        )
        result_str = answer.strip()
        if "```" in result_str:
            result_str = extract_code(result_str, code_type="json")
        result = state["result"]
        try:
            result = json.loads(result_str)
        except Exception:
            error = traceback.format_exc()
            print(f"failed to parse `result_str` in reporter: {error}")

        prompt = f"""Make a Markdown summary based on the following information.
At the begining of the report, please introduce the image of the graph architecture at `graph.png`.
This graph represents how the Chief Information Security Officer (CISO) Agent performs to achieve the requested goal.
Your answer will be saved as a Markdown file later.

Goal: {goal}

{policy_block}

Result:
{result}
"""

        answer = call_llm(
            prompt=prompt,
            model=manager_model,
            api_key=manager_api_key,
            api_url=manager_api_url,
        )
        report = answer.strip()
        if "```markdown" in report:
            report = report.lstrip("```markdown").rstrip("```")

        opath = os.path.join(workdir, "report.md") if workdir else "report.md"
        with open(opath, "w") as f:
            f.write(report)
        result["path_to_generated_report"] = opath

        return {"summary": report, "result": result}
