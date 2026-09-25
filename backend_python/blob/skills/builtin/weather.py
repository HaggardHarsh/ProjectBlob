import urllib.request
from blob.skills.base import SkillInterface, SkillResult

class WeatherSkill(SkillInterface):
    @property
    def name(self): return "weather"
    
    @property
    def description(self): return "Get the current weather"
    
    @property
    def triggers(self): return ["weather", "forecast"]
    
    def execute(self, args):
        try:
            req = urllib.request.Request("https://wttr.in/?format=3", headers={'User-Agent': 'curl/7.0.0'})
            res = urllib.request.urlopen(req).read().decode('utf-8')
            return SkillResult(output=res, success=True, emote_suggestion="HAPPY")
        except Exception as e:
            return SkillResult(output=str(e), success=False, emote_suggestion="WORRIED")
