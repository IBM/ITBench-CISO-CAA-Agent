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

import argparse
import datetime
import json
import os
import shutil
import string
import sys

from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv
from langtrace_python_sdk import langtrace

from ciso_agent.llm import init_agent_llm, extract_code
from ciso_agent.tools.generate_kyverno import GenerateKyvernoTool
from ciso_agent.tools.run_kubectl import RunKubectlTool


load_dotenv()

if os.getenv("LANGTRACE_API_HOST"):
    langtrace.init(
        api_host=os.getenv("LANGTRACE_API_HOST"),
        api_key=os.getenv("LANGTRACE_API_KEY"),
    )


class KubernetesKyvernoUpdateCrew(object):
    agent_goal: str = """Currently, the following Kyverno policies are deployed in the Kubernetes cluster.
Review these existing policies and edit them to meet additional security requirements.
Please avoid creating new policy resources; instead, make the necessary changes directly to the existing resources.

${current_compliance}

However, the new internal security policy now requires the following additional conditions:

${updated_compliance}

Your task is to review the existing Kyverno policies and directly edit the existing policies to meet these new requirements.
Do not change the resource names. Once you have completed the edits, update the existing resources in the Kubernetes cluster.
Steps
- Get Kyverno policies and review them.
- Generate an updated Kyverno policy to meet the new requirements based on the current one. Ensure that you do not change the names of the resources.
- Apply the updated one to the cluster.

Once you get a final answer, you can quit the work.
"""
    tool_description: str = """This agent has the following tools to use:
- RunKubectlTool
- GenerateKyvernoTool
"""

    input_description: dict = {
        "current_compliance": "a short string of current compliance requirement",
        "updated_compliance": "a short string of updated compliance requirement in addition to the current one",
        "workdir": "a working directory to save temporary files",
    }

    output_description: dict = {
        "updated_resource": "a dict of Kubernetes metadata for the updated Kyverno policy",
        "path_to_generated_kyverno_policy": "a string of the filepath to the generated Kyverno policy YAML",
    }

    workdir_root: str = "/tmp/agent/"

    def kickoff(self, inputs: dict):
        return self.run_scenario(**inputs)

    def run_scenario(self, goal: str, **kwargs):
        workdir = kwargs.get("workdir")
        if not workdir:
            workdir = os.path.join(self.workdir_root, datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S_"), "workspace")

        if not os.path.exists(workdir):
            os.makedirs(workdir, exist_ok=True)

        if "kubeconfig" in kwargs and kwargs["kubeconfig"]:
            kubeconfig = kwargs["kubeconfig"]
            dest = os.path.join(workdir, "kubeconfig.yaml")
            if kubeconfig != dest:
                shutil.copy(kubeconfig, dest)

        llm = init_agent_llm()
        test_agent = Agent(
            role="Test",
            goal=goal,
            backstory="",
            llm=llm,
            verbose=True,
        )

        target_task = Task(
            name="target_task",
            description="""Get the Kyverno policy and generate the updated one based on it. Then deploy it on the cluster.""",
            expected_output="""A boolean which indicates if the result is OK or not""",
            agent=test_agent,
            tools=[
                RunKubectlTool(workdir=workdir, read_only=False),
                GenerateKyvernoTool(workdir=workdir),
            ],
        )
        report_task = Task(
            name="report_task",
            description="""Report a filepath that was created in the previous task.
You must not replay the steps in the privious task such as generating code / running something.
Just to report the result.
""",
            expected_output="""A JSON string with the following info:
```json
{
    "updated_resource": {
        "namespace": <PLACEHOLDER>,
        "kind": <PLACEHOLDER>,
        "name": <PLACEHOLDER>
    },
    "path_to_generated_kyverno_policy": <PLACEHOLDER>,
}
```
You can omit `namespace` in `updated_resource` if the policy is a cluster-scope resource.
""",
            context=[target_task],
            agent=test_agent,
        )

        crew = Crew(
            name="CISOCrew",
            tasks=[
                target_task,
                report_task,
            ],
            agents=[
                test_agent,
            ],
            process=Process.sequential,
            verbose=True,
            cache=False,
        )
        inputs = {}
        output = crew.kickoff(inputs=inputs)
        result_str = output.raw.strip()
        if not result_str:
            raise ValueError("crew agent returned an empty string.")

        if "```" in result_str:
            result_str = extract_code(result_str, code_type="json")
        result_str = result_str.strip()

        if not result_str:
            raise ValueError(f"crew agent returned an invalid string. This is the actual output: {output.raw}")

        result = {}
        try:
            result = json.loads(result_str)
        except Exception:
            print(f"Failed to parse this as JSON: {result_str}", file=sys.stderr)

        # add workdir prefix here because agent does not know it
        for key, val in result.items():
            if val and key.startswith("path_to_") and "/" not in val:
                result[key] = os.path.join(workdir, val)

        return {"result": result}


if __name__ == "__main__":
    default_compliance = "Ensure that the cluster-admin role is only used where required"
    parser = argparse.ArgumentParser(description="TODO")
    parser.add_argument("-c", "--current-compliance", default=default_compliance, help="The compliance description for the agent to do something for")
    parser.add_argument(
        "-u", "--updated-compliance", default=default_compliance, help="The additional compliance description for the agent to do something for"
    )
    parser.add_argument("-k", "--kubeconfig", required=True, help="The path to the kubeconfig file")
    parser.add_argument("-w", "--workdir", default="", help="The path to the work dir which the agent will use")
    parser.add_argument("-o", "--output", help="The path to the output JSON file")
    args = parser.parse_args()

    if args.workdir:
        os.makedirs(args.workdir, exist_ok=True)

    if args.kubeconfig:
        dest_path = os.path.join(args.workdir, "kubeconfig.yaml")
        shutil.copyfile(args.kubeconfig, dest_path)

    inputs = dict(
        current_compliance=args.current_compliance,
        updated_compliance=args.updated_compliance,
        workdir=args.workdir,
    )
    _result = KubernetesKyvernoUpdateCrew().kickoff(inputs=inputs)
    result = _result.get("result")

    result_json_str = json.dumps(result, indent=2)

    print("---- Result ----")
    print(result_json_str)
    print("----------------")

    if args.output:
        with open(args.output, "w") as f:
            f.write(result_json_str)
