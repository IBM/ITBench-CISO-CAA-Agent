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
import re
import subprocess
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from ciso_agent.tools.utils import trim_quote


class RunPlaybookToolInput(BaseModel):
    host: str = Field(description="The hostname where the Playbook should be executed")
    playbook_file: str = Field(description="Playbook filepath to be run")


class RunPlaybookTool(BaseTool):
    name: str = "RunPlaybookTool"
    # correct description
    description: str = """The tool to run a playbook on a given host.
This tool returns the following:
  - return_code: if 0, the command was successful, otherwise, failure.
  - stdout: standard output of the command
  - stderr: standard error of the command (only when error occurred)
"""

    args_schema: type[BaseModel] = RunPlaybookToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]

    def _run(self, host: str, playbook_file: str) -> str:
        print("RunPlaybookTool is called")
        playbook_file = trim_quote(playbook_file)

        code = ""
        fpath = os.path.join(self.workdir, playbook_file)
        with open(fpath, "r") as f:
            code = f.read()
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if line.strip().lstrip("- ").startswith("hosts"):
                new_line = re.sub("hosts: .*", f"hosts: {host}", line)
                lines[i] = new_line
        code = "\n".join(lines) + "\n"
        with open(fpath, "w") as f:
            f.write(code)

        print("[DEBUG] Running this playbook:", code)

        cmd_str = f"ansible-playbook {playbook_file} -i inventory.ansible.ini"
        proc = subprocess.run(
            cmd_str,
            shell=True,
            cwd=self.workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print("[DEBUG] ansible-playbook result returncode:", proc.returncode)
        print("[DEBUG] ansible-playbook result stdout:", proc.stdout)
        print("[DEBUG] ansible-playbook result stderr:", proc.stderr)
        # if proc.returncode != 0:
        #     raise ValueError(f"failed to run a playbook; stdout: {proc.stdout}, stderr: {proc.stderr}")
        result = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
        }
        if proc.returncode != 0:
            result["stderr"] = proc.stderr
        return result

