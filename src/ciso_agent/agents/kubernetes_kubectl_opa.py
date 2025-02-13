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

from crewai import Agent, Crew, Process, Task
from dotenv import load_dotenv
from langtrace_python_sdk import langtrace

from ciso_agent.llm import init_agent_llm, extract_code
from ciso_agent.tools.generate_opa_rego import GenerateOPARegoTool
from ciso_agent.tools.run_opa_rego import RunOPARegoTool
from ciso_agent.tools.run_kubectl import RunKubectlTool


load_dotenv()

if os.getenv("LANGTRACE_API_HOST"):
    langtrace.init(
        api_host=os.getenv("LANGTRACE_API_HOST"),
        api_key=os.getenv("LANGTRACE_API_KEY"),
    )


class KubernetesKubectlOPACrew(object):
    agent_goal: str = """I would like to check if the following condition is satisfiled, given a Kubernetes cluster with `kubeconfig.yaml`
    ${compliance}

To check the condition, do the following steps.
- get related resource(s) on the cluster by kubectl command and save it as `collected_data.json`
- chcek if the conditions are satisfied by OPA Rego policy

for those steps, you need to create an OPA Rego policy `policy.rego`.
Also, save the kubectl command as `script.sh`.

If running the policy failed and if you can fix the issue, you will do it and try running again.

Once you get a final answer, you can quit the work.
"""

    tool_description: str = """This agent has the following tools to use:
- RunOPARegoTool
- GenerateOPARegoTool
- RunKubectlTool
"""

    input_description: dict = {
        "compliance": "a short string of compliance requirement",
        "workdir": "a working directory to save temporary files",
    }

    output_description: dict = {
        "path_to_generated_shell_script": "a string of the filepath to the generated shell script",
        "path_to_generated_rego_policy": "a string of the filepath to the generated rego policy",
        "path_to_collected_data_by_script": "a string of the filepath to the collected data",
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
            description="""Check a rego policy for a given input file. If policy or input file are not ready, prepare them first.""",
            expected_output="""A boolean which indicates if the check is passed or not""",
            agent=test_agent,
            tools=[
                RunOPARegoTool(workdir=workdir),
                GenerateOPARegoTool(workdir=workdir),
                RunKubectlTool(workdir=workdir, read_only=True),
            ],
        )
        report_task = Task(
            name="report_task",
            description="""Report filepaths that are created in the previous task.
You must not replay the steps in the privious task such as generating code / running something.
Just to report the result.
""",
            expected_output="""A JSON string with the following info:
```json
{
    "path_to_generated_shell_script": <PLACEHOLDER>,
    "path_to_generated_rego_policy": <PLACEHOLDER>,
    "path_to_collected_data_by_script": <PLACEHOLDER>,
}
```
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
        )
        inputs = {}
        output = crew.kickoff(inputs=inputs)
        result_str = output.raw
        if "```" in result_str:
            result_str = extract_code(result_str, code_type="json")

        result = None
        try:
            result = json.loads(result_str)
        except Exception:
            raise ValueError(f"Failed to parse this as JSON: {result_str}")

        # add workdir prefix here because agent does not know it
        for key, val in result.items():
            if val and key.startswith("path_to_") and "/" not in val:
                result[key] = os.path.join(workdir, val)

        # for eval, copy the generated files to some fixed filepath (filename)
        copy_files_for_eval(result)

        return {"result": result}


def copy_files_for_eval(result: dict):
    script_path = result.get("path_to_generated_shell_script")
    if script_path and os.path.exists(script_path) and os.path.basename(script_path) != "fetcher.sh":
        dest_path = os.path.join(os.path.dirname(script_path), "fetcher.sh")
        shutil.copyfile(script_path, dest_path)

    policy_path = result.get("path_to_generated_rego_policy")
    if policy_path and os.path.exists(script_path) and os.path.basename(policy_path) != "policy.rego":
        dest_path = os.path.join(os.path.dirname(policy_path), "policy.rego")
        shutil.copyfile(policy_path, dest_path)

    data_path = result.get("path_to_collected_data_by_script")
    if data_path and os.path.exists(script_path) and os.path.basename(data_path) != "collected_data.json":
        dest_path = os.path.join(os.path.dirname(data_path), "collected_data.json")
        shutil.copyfile(data_path, dest_path)
    return


if __name__ == "__main__":
    default_compliance = "Ensure that the cluster-admin role is only used where required"
    parser = argparse.ArgumentParser(description="TODO")
    parser.add_argument("-c", "--compliance", default=default_compliance, help="The compliance description for the agent to do something for")
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
        compliance=args.compliance,
        workdir=args.workdir,
    )
    _result = KubernetesKubectlOPACrew().kickoff(inputs=inputs)
    result = _result.get("result")

    result_json_str = json.dumps(result, indent=2)

    print("---- Result ----")
    print(result_json_str)
    print("----------------")

    if args.output:
        with open(args.output, "w") as f:
            f.write(result_json_str)
