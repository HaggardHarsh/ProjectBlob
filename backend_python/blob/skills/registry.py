class SkillRegistry:
    def __init__(self):
        self.skills = {}
        
    def register(self, skill):
        self.skills[skill.name] = skill
        
    def get_skill(self, name):
        return self.skills.get(name)
