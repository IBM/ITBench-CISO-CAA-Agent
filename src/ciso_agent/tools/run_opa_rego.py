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
import subprocess
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from ciso_agent.tools.utils import trim_quote


class RunOPARegoToolInput(BaseModel):
    policy_file: str = Field(description="Rego policy filepath to be evaluated")
    input_file: str = Field(description="The filepath to the input data to be used for checking the policy")


class RunOPARegoTool(BaseTool):
    name: str = "RunOPARegoTool"
    # correct description
    description: str = "The tool to run OPA Rego evaluation. This tool returns the check result."

    args_schema: type[BaseModel] = RunOPARegoToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]

    def _run(self, policy_file: str, input_file: str) -> str:
        print("RunOPARegoTool is called")
        policy_file = trim_quote(policy_file)
        input_file = trim_quote(input_file)

        fpath = os.path.join(self.workdir, policy_file)
        rego_pkg_name = get_rego_main_package_name(rego_path=fpath)
        if not rego_pkg_name:
            raise ValueError("`package` must be defined in the rego policy file")

        input_data = ""
        ipath = os.path.join(self.workdir, input_file)
        with open(ipath, "r") as f:
            input_data = f.read()

        cmd_str = f"opa eval --data {policy_file} --stdin-input 'data.{rego_pkg_name}'"
        proc = subprocess.run(
            cmd_str,
            shell=True,
            cwd=self.workdir,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        input_data_to_show = input_data
        truncated_msg = ""
        if len(input_data_to_show) > 1000:
            input_data_to_show = input_data_to_show[:1000]
            truncated_msg = " (truncated)"
        print(f"command: {cmd_str}")
        print(f"proc.input_data{truncated_msg}: {input_data_to_show}")
        print(f"proc.stdout: {proc.stdout}")
        print(f"proc.stderr: {proc.stderr}")

        if proc.returncode != 0:
            error = f"failed to run `opa eval` command; error details:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            raise ValueError(error)

        result = json.loads(proc.stdout)
        if "result" not in result:
            raise ValueError(f"`result` field does not exist in the output from `opa eval` command; raw output: {proc.stdout}")

        result_arr = result["result"]
        if not result_arr:
            raise ValueError(f"`result` field in the output from `opa eval` command has no contents; raw output: {proc.stdout}")

        first_result = result_arr[0]
        if not first_result and "expressions" not in first_result:
            raise ValueError(
                f"`expressions` field does not exist in the first result of output from `opa eval` command; first_result: {first_result}"
            )

        expressions = first_result["expressions"]
        if not expressions:
            raise ValueError(f"`expressions` field in the output from `opa eval` command has no contents; first_result: {first_result}")

        expression = expressions[0]
        result_value = expression.get("value", {})
        eval_result = {
            "value": result_value,
            "message": proc.stderr,
        }
        print(eval_result)
        return eval_result


def get_rego_main_package_name(rego_path: str):
    pkg_name = ""
    with open(rego_path, "r") as file:
        prefix = "package "
        for line in file:
            _line = line.strip()
            if _line.startswith(prefix):
                pkg_name = _line[len(prefix) :]
                break
    return pkg_name
