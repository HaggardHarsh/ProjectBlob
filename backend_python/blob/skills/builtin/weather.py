import urllib.request
from urllib.parse import quote_plus
from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema

class WeatherSkill(SkillInterface):
    argument_schema = object_schema({"location": {"type": "string", "maxLength": 120, "default": ""}})
    permissions = ("network.http",)
    @property
    def name(self): return "weather"
    
    @property
    def description(self): return "Get current weather. Optional args: {'location': 'city name'}; omit location for IP-based location"
    
    @property
    def triggers(self): return ["weather"]
    
    def execute(self, args):
        location = args.get("location", "")
        if not isinstance(location, str) or len(location) > 120:
            return SkillResult("Location must be a short city name.", False, "CONFUSED")
        location = location.strip()
        url = f"https://wttr.in/{quote_plus(location, safe='')}?format=3"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.0.0'})
            response = urllib.request.urlopen(req, timeout=10)
            try:
                res = response.read(8193).decode('utf-8', errors="replace").strip()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if len(res.encode("utf-8")) > 8192:
                return SkillResult("Weather service returned too much data. Try again later.", False, "WORRIED")
            if not res or "unknown location" in res.lower():
                return SkillResult("Weather service could not find that location.", False, "WORRIED")
            return SkillResult(output=res, success=True, emote_suggestion="HAPPY")
        except Exception as e:
            return SkillResult(output=str(e), success=False, emote_suggestion="WORRIED")
