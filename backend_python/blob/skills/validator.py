import yaml
from dataclasses import dataclass

@dataclass
class SkillDefinition:
    name: str
    description: str

class SkillValidator:
    def validate(self, yaml_content: str) -> SkillDefinition:
        data = yaml.safe_load(yaml_content)
        if 'name' not in data or 'description' not in data:
            raise ValueError("Invalid skill definition")
        return SkillDefinition(name=data['name'], description=data['description'])
