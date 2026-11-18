# John's brain: sends what the user said to Claude with John's tools, runs the tools Claude asks for, and returns the
# answer to speak. A conversation carries on for follow-ups and starts fresh after a few quiet minutes.
import datetime
import logging
import re
import anthropic
from nestor.john_tools import JohnTools
CONVERSATION_GAP = datetime.timedelta(minutes=5)  # A longer pause starts a new conversation
MAX_ROUNDS = 8  # Tool calls in one answer before giving up
FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_ANSWER = "Sorry, I can't help with that one."
SYSTEM_PROMPT = (
    "You are John, the voice assistant in OWNER's home. You run on Nestor, OWNER's own home system, and you speak "
    "through a Google speaker, so everything you write is read aloud.\n"
    "\n"
    "How to answer:\n"
    "- Answer in one to three short sentences of plain speech. No lists, markdown, emoji, links or headings.\n"
    "- Say times like \"7:30 PM\" and dates like \"Friday, November 20\". Round numbers when exact digits don't "
    "matter.\n"
    "- If you didn't understand or something is missing, ask one short question.\n"
    "\n"
    "What you can do:\n"
    "- Datebook is OWNER's phone app for plans. datebook_overview has their calendar, plans waiting to be added, "
    "bills, assignments, packages, trips, notes, Datebook reminders and train trip. Use it for any question about "
    "their schedule or those lists.\n"
    "- To put something into Datebook (a plan, a Datebook reminder or a note), use datebook_action with new_plan and "
    "OWNER's words; the phone then shows Datebook's prompt, so say to confirm it there. Only change Datebook when "
    "asked, but when a plan comes up in passing, you may offer to send it to Datebook.\n"
    "- For \"remind me\" without mentioning Datebook or the phone, use add_reminder: Nestor speaks it here at home.\n"
    "- \"Start my day\" and \"goodnight\" each have their own tool that speaks a full briefing; after using one, reply "
    "with nothing at all.\n"
    "- Use web_search for current facts, news, sports, prices and anything you aren't sure of.\n"
    "- Use remember and forget when asked to remember or forget something, and to note lighting OWNER liked.\n"
    "- Timers and alarms ring on the speaker: for \"wake me at 7\" set an alarm, for a length of time a timer.\n"
    "- next_trains has live NJ Transit trains; with no stations named it uses the saved trip.\n"
    "- Lights: set_lights for plain requests (\"lights to blue\", \"30 percent\", \"off\"); focus mode is a cool "
    "blue steady light.\n"
    "- The lights are in groups: the wall (a strip) and the living room lights (two bulbs that always go together). "
    "\"Lights\" alone means all of them.\n"
    "- Moods: only when OWNER asks for lighting for something (\"I want lights for a movie I'm watching\", \"set the "
    "mood for movie night\"); just mentioning what they're doing isn't a request. Then have a real back-and-forth. "
    "First ask one or two short questions, one at a time (what kind of movie, cozy or lively, bright or dim), unless "
    "you remember what they like for it. Then show ONE look at a time with preview_mood, with a fun name you make "
    "up: say the name, describe it in a few words, and ask what they think. They can say \"next\" (a new look), \"go "
    "back\" (the previous look again, same settings), tweak it (\"warmer\", \"slower\", \"more purple\", \"dimmer\": "
    "use adjust_mood), or \"that one\". When they keep a look, remember in a few words what they liked for that "
    "activity, and offer to save it by name; list_moods and use_mood bring saved ones back.\n"
    "- Music is coming soon; until then say briefly that you can't do that yet.\n"
    "\n"
    "Each message starts with a bracketed line from Nestor with the current time and status; it isn't part of what "
    "OWNER said, so don't repeat it back.")
log = logging.getLogger(__name__)

# The text of Claude's answer, cleaned for speaking (no markdown marks or links)
def spoken_answer(response):
    text = " ".join(block.text for block in response.content if block.type == "text").strip()
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"[*_#`>]+", "", text).strip()

# Holds the conversation with Claude and runs John's tools
class Brain:
    # Connect to Claude with Nestor's own API key; rail is the NJ Transit account for trains (None without one)
    def __init__(self, announcer, settings, api_key, rail=None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.system_prompt = SYSTEM_PROMPT.replace("OWNER", settings.get("john_owner_name") or "the user")
        self.model = settings.get("john_model", "claude-opus-5-5")
        self.effort = settings.get("john_effort", "low")
        self.tools = JohnTools(announcer, settings, rail)
        self.messages = []
        self.last_turn = None

    # Answer what was said; returns the text to speak ("" when a tool already spoke, e.g. goodnight)
    def ask(self, heard, now=None):
        now = now or datetime.datetime.now()
        first_turn = self.last_turn is None or now - self.last_turn > CONVERSATION_GAP

        # A long pause means a new conversation
        if first_turn:
            self.messages = []
        self.messages.append({"role": "user", "content": f"{self.tools.context(now, first_turn)}\n{heard}"})

        # Ask Claude, keeping the conversation only if the answer worked
        try:
            answer = self.run_turn()
        except Exception:
            self.messages = []
            raise
        finally:
            self.last_turn = datetime.datetime.now()
        return answer

    # Call Claude until it stops asking for tools; returns the answer to speak
    def run_turn(self):
        # Each round: Claude answers or asks for tools, whose results go back for the next round
        for round_number in range(MAX_ROUNDS):
            response = self.client.beta.messages.create(
                model=self.model, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
                system=self.system_prompt, tools=self.tools.definitions, messages=self.messages,
                output_config={"effort": self.effort}, cache_control={"type": "ephemeral"})
            self.messages.append({"role": "assistant", "content": response.content})
            tool_calls = [block for block in response.content if block.type == "tool_use"]

            # A refusal ends the conversation; a paused web search carries on; tools run; otherwise it's the answer
            if response.stop_reason == "refusal":
                log.info("Claude declined: %s", response.stop_details)
                self.messages = []
                return REFUSAL_ANSWER
            elif response.stop_reason == "pause_turn":
                continue
            elif response.stop_reason == "tool_use" and tool_calls:
                log.info("John uses %s", ", ".join(block.name for block in tool_calls))
                self.messages.append({"role": "user", "content": [self.tools.run(block) for block in tool_calls]})
            else:
                return spoken_answer(response)
        return "Sorry, that took too many steps. Could you ask in a simpler way?"
