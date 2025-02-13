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

import os
import subprocess
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from ciso_agent.tools.utils import trim_quote


class RunKubectlToolInput(BaseModel):
    args: str = Field(
        description="command arguments after `kubectl`. `--kubeconfig` should be specified here. Multiple commands with `;` or `&&` is not allowed."
    )
    output_file: str = Field(description="The filepath to save the result. If empty string, not save anything", default="")
    return_output: str = Field(description='A boolean string. Set this to "True" if you want to get the command output', default="False")
    script_file: str = Field(description="A filepath. If provided, save the kubectl command as a script at the specified file.", default="")


class RunKubectlTool(BaseTool):
    name: str = "RunKubectlTool"
    # correct description
    description: str = """The tool to execute a kubectl command.
This tool returns the following:
  - return_code: if 0, the command was successful, otherwise, failure.
  - stdout: standard output of the command (only when `return_output` is True)
  - stderr: standard error of the command (only when error occurred)
  - script_file: saved script path if applicable

For example, to execute `kubectl get pod -n default --kubeconfig kubeconfig.yaml`,
Tool Input should be the following:
{"args": "get pod -n default --kubeconfig kubeconfig.yaml", "output_file": "", "return_output": "True", "script_file": ""}

Hint:
- If you need to get all pods in all namespaces, you can do it by `kubectl get pods --all-namespaces --kubeconfig <kubeconfig_path> -o json`
"""
    args_schema: type[BaseModel] = RunKubectlToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""
    read_only: bool = True

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir", "read_only"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]
        if "read_only" in kwargs:
            self.read_only = kwargs["read_only"]

    def _run(self, args: str, output_file: str, return_output: str = "False", script_file: str = "") -> str:
        print("RunKubectlTool is called")
        output_file = trim_quote(output_file)
        script_file = trim_quote(script_file)

        if "--kubeconfig" not in args:
            raise ValueError("--kubeconfig must be specified to avoid touching wrong cluster")

        if output_file and output_file.endswith(".json"):
            if "-o" not in args and "--output" not in args:
                args += " -o json"

        # remove if `kubectl` is included in the given args
        parts = args.strip().split(" ", 1)
        if len(parts) > 1 and "kubectl" in parts[0]:
            args = parts[1]

        if self.read_only:
            if not args.strip().startswith("get"):
                raise ValueError("Only `get` operation is allowed")

        cmd_str = f"kubectl {args}"
        print("[DEBUG] Running this command:", cmd_str)
        proc = subprocess.run(
            cmd_str,
            shell=True,
            cwd=self.workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        std_out = proc.stdout
        if len(std_out) > 1000:
            std_out = std_out[:1000] + "\n\n...Output is too long. Truncated here."

        std_err = proc.stderr
        if len(std_err) > 1000:
            std_err = std_err[:1000] + "\n\n...Output is too long. Truncated here."

        print("[DEBUG] kubectl result returncode:", proc.returncode)
        print("[DEBUG] kubectl result stdout:", std_out)
        print("[DEBUG] kubectl result stderr:", std_err)
        # if proc.returncode != 0:
        #     raise ValueError(f"failed to run a playbook; stdout: {proc.stdout}, stderr: {proc.stderr}")

        if output_file:
            opath = os.path.join(self.workdir, output_file)
            with open(opath, "w") as f:
                f.write(proc.stdout)

        return_output_bool = False
        if return_output:
            if isinstance(return_output, str):
                return_output_bool = return_output.lower() == "true"

        return_val = {"return_code": proc.returncode}
        if return_output_bool:
            return_val["stdout"] = std_out
        if proc.returncode != 0:
            return_val["stderr"] = std_err

        if script_file:
            cmd_str_ext = cmd_str
            if output_file:
                cmd_str_ext += f" > {output_file}"
            script_body = f"""#!/bin/bash
{cmd_str_ext}
"""
            spath = script_file
            if "/" not in script_file:
                spath = os.path.join(self.workdir, script_file)
            with open(spath, "w") as f:
                f.write(script_body)
            os.chmod(spath, 0o755)
            
            return_val["script_file"] = spath

        return return_val
