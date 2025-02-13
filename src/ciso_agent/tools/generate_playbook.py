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
from typing import Callable, Union

from ciso_agent.llm import call_llm, extract_code
from ciso_agent.tools.utils import trim_quote
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class GeneratePlaybookToolInput(BaseModel):
    sentence: Union[str, dict] = Field(
        description=(
            "A short description of Ansible Playbook to be generated. This includes the compliance requirement. "
            "This includes what is accomplished with the Playbook execution."
        )
    )
    playbook_file: str = Field(description="A filepath for the Playbook to be saved.", default="playbook.yml")


class GeneratePlaybookTool(BaseTool):
    name: str = "GeneratePlaybookTool"
    # correct description
    description: str = "The tool to generate a Playbook. This tool returns the generated Playbook."

    args_schema: type[BaseModel] = GeneratePlaybookToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]

    def _run(self, sentence: Union[str, dict], playbook_file: str = "playbook.yml") -> str:
        print("GeneratePlaybookTool is called")
        playbook_file = trim_quote(playbook_file)

        spec = sentence
        if isinstance(spec, dict):
            try:
                spec = json.dumps(spec, indent=2)
            except Exception:
                pass
        prompt = f"""Generate a very simple Ansible Playbook to do the following:
{spec}


Points:
- You should save a detailed info. Not a boolean of the check result.
- To read/write OS level files (e.g. under `/etc` dir), you should add `become: true`. Use grep.
- Do not use `setup` module.
- To save a variable in the playbook, you can use this task.
    ```yaml
    - name: Save a variable content in a localhost
      copy:
        content: {{{{ variable_name | quote }}}}
        dest: collected_data.json
      delegate_to: localhost
      become: false
    ```
  If you try to save a registered variable, do not parse it. Just save it as is.
  `become: false` is necessary for this task because you don't have sudo permission on localhost.
  Use "collected_data.json" and do not change the destination file name.
- Do not try to find "collected_data.json" when not found. Just collect the data again.
- Do not specify absolute path anywhere. You must use the current directory.
- If you need command result as a collected data, you should add `ignore_errors: true` to the task.
- Use Ansible module instead of command, if possible.
"""
        model = os.getenv("CODE_GEN_MODEL")
        api_key = os.getenv("CODE_GEN_API_KEY")
        print(f"Generating Playbook code with '{model}'")
        print("Prompt:", prompt)
        answer = call_llm(prompt, model=model, api_key=api_key)
        code = extract_code(answer, code_type="yaml")
        playbook_file = playbook_file.strip('"').strip("'").lstrip("{").rstrip("}")
        if not playbook_file:
            playbook_file = "playbook.yaml"
        fpath = os.path.join(self.workdir, playbook_file)
        with open(fpath, "w") as f:
            f.write(code)
        print("Code in answer:", code)

        tool_output = f"""The generated Playbook is below:
```yaml
{code}
```

This Playbook file has been saved at {fpath}.
"""
        return code
