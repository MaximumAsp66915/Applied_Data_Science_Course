import asyncio
from functools import wraps
from typing import Optional, Union, Any, Callable

from db.internal_db.SUTMusic.reaction_type_internal_db import Internal_DB_ReactionType
from utils.result import Result
from utils.schedule.dict_helper import AutoExpiringDict

LIST_OF_DICT_FIELDS = set()
DICT_FIELDS = set()
SCALAR_FIELDS = {
    "id"
    "emoji",
    "sentiment",
    "score",
    "description",
}

_in = Internal_DB_ReactionType()

reaction_param_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=1000)


def make_hashable(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in obj.items()))
    elif isinstance(obj, list):
        return tuple(make_hashable(i) for i in obj)
    elif isinstance(obj, set):
        return tuple(sorted(make_hashable(i) for i in obj))
    elif isinstance(obj, tuple):
        return tuple(make_hashable(i) for i in obj)
    else:
        return obj


def build_cache_key(self, prefix: Optional[str], args: tuple, kwargs: dict, extra: tuple = ()) -> tuple:
    return (
        self.reaction_type_id,
        prefix,
        make_hashable(extra),
    )


def cache_result(prefix: Optional[str] = None, extra_key: Optional[Callable[[tuple, dict], tuple]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            extra = extra_key(args, kwargs) if extra_key else ()
            key = build_cache_key(self, prefix, args, kwargs, extra)

            cached = await reaction_param_cache.get(key)
            if cached is not None:
                return cached

            result = await func(self, *args, **kwargs)
            if result is not None:
                await reaction_param_cache.set(key, result)
            return result

        return wrapper

    return decorator


def cache_update_dynamic(
    prefix: str,
    get_field: Callable[[tuple, dict], Any],
    get_value: Callable[[tuple, dict], Any],
    extra_key: Optional[Callable[[tuple, dict], tuple]] = None,
):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            result = await func(self, *args, **kwargs)

            if result is None or (isinstance(result, Result) and result.success):
                try:
                    value = get_value(args, kwargs)
                    extra = extra_key(args, kwargs) if extra_key else ()
                    key = build_cache_key(self, prefix, args, kwargs, extra)
                    await reaction_param_cache.set(key, value)
                except Exception as e:
                    print(f"[⚠️ cache_update_dynamic] Failed to cache at reaction func: {func.__name__} : {e}")
            return result

        return wrapper

    return decorator


class ReactionType:
    _lock = asyncio.Lock()

    def __init__(self, reaction_type_id: Optional[int] = None) -> None:
        self.reaction_type_id = reaction_type_id

    @classmethod
    async def get_by_id(cls, reaction_type_id: Union[int]) -> Optional["ReactionType"]:
        obj = await _in.get_reaction_by_id(int(reaction_type_id))
        if obj:
            return ReactionType(obj.reaction_type_id)
        return None

    @classmethod
    async def get_by_emoji(cls, emoji: str) -> Optional["ReactionType"]:
        obj = await _in.get_reaction_by_emoji(emoji)
        if obj:
            return ReactionType(obj.reaction_type_id)
        return None

    @classmethod
    async def search_reactions(
        cls,
        conditions: dict,
        fuzzy: bool = False,
        similarity_threshold: float = 0.7,
        limit: int = 10,
        order_by: str = "id",
        descending: bool = False,
    ) -> Optional[list["ReactionType"]]:
        objs = await _in.search_reactions(
            conditions=conditions,
            fuzzy=fuzzy,
            similarity_threshold=similarity_threshold,
            limit=limit,
            order_by=order_by,
            descending=descending,
        )
        if objs:
            return [ReactionType(obj.reaction_type_id) for obj in objs]
        return None

    # UPDATED: Added score parameter with default 0.0
    @classmethod
    async def create(
        cls,
        emoji: str,
        sentiment: str,
        score: float = 0.0,
        description: Optional[str] = None
    ) -> Result:
        if sentiment not in ("like", "dislike", "neutral"):
            return Result(False, "create", f"Invalid sentiment check restraint: {sentiment}", None)

        new_reaction = {
            "emoji": emoji,
            "sentiment": sentiment,
            "score": score,
            "description": description,
        }

        result = await _in.add_reaction(new_reaction)
        if result.success:
            reaction_type_id = result.data
            result.data = ReactionType(reaction_type_id)
        return result


    # -------------------- Cached methods --------------------
    @cache_result(prefix="reaction_param", extra_key=lambda args, kwargs: (args[0],))
    async def get_parameter(self, param: str) -> Any:
        result = await _in.get_parameter_from_db(self.reaction_type_id, param)
        if not result.success or result.data is None:
            return None
        return result.data

    @cache_update_dynamic(
        prefix="reaction_param",
        get_field=lambda args, kwargs: args[0],
        get_value=lambda args, kwargs: args[1],
        extra_key=lambda args, kwargs: (args[0],),
    )
    async def update_parameter(self, param: str, value: Any) -> Result:
        if param == "sentiment" and value not in ("like", "dislike", "neutral"):
            return Result(False, "update_parameter", f"Invalid sentiment check restraint: {value}", None)

        result = Result(True, "update_parameter", "", None)
        if param in SCALAR_FIELDS:
            await result.add_sub_result(await _in.update_parameter(self.reaction_type_id, param, value))
        else:
            return Result(False, "update_parameter", f"Unknown parameter: {param}", None)

        return result

    async def erase_parameter(self, param: str) -> Result:
        if param == "description":
            return await _in.update_parameter(self.reaction_type_id, param, None)
        # score shouldn't be erased/nulled arbitrarily due to logic context, so it fails here safely.
        return Result(False, "erase_parameter", f"Cannot clear or null primary key/required structural parameter: {param}", None)

    async def delete(self) -> Result:
        return await _in.delete_reaction_by_emoji(self.reaction_type_id)

    @staticmethod
    async def seed_reaction_types():
        # --- EMOTIONALLY ENGAGED / POSITIVE SENTIMENTS (LIKE) ---
        await ReactionType.create(emoji="❤️", sentiment="like", score=4.0, description="Love / Deep Affection")
        await ReactionType.create(emoji="🔥", sentiment="like", score=4.5, description="Fire / Viral Hit")
        await ReactionType.create(emoji="💯", sentiment="like", score=4.0, description="Perfect / Masterpiece")
        await ReactionType.create(emoji="❤️‍🔥", sentiment="like", score=5.0, description="Passionate / Intense")
        await ReactionType.create(emoji="🚀", sentiment="like", score=3.5, description="Energizing / Banger")
        await ReactionType.create(emoji="👑", sentiment="like", score=3.5, description="Goat Track")
        await ReactionType.create(emoji="🏆", sentiment="like", score=3.0, description="Award Worthy")
        await ReactionType.create(emoji="🥰", sentiment="like", score=4.0, description="Heart-warming")
        await ReactionType.create(emoji="🤩", sentiment="like", score=4.5,
                                  description="Star-Struck / Amazing Production")
        await ReactionType.create(emoji="🎉", sentiment="like", score=4.0, description="Party / Dance Vibe")
        await ReactionType.create(emoji="💖", sentiment="like", score=4.5, description="Sparkling / High Production")
        await ReactionType.create(emoji="💞", sentiment="like", score=4.5, description="Resonating Hearts")
        await ReactionType.create(emoji="💓", sentiment="like", score=4.5, description="High Energy / Heart-pounding")
        await ReactionType.create(emoji="💗", sentiment="like", score=4.5, description="Growing Emotional Connection")
        await ReactionType.create(emoji="💝", sentiment="like", score=4.5, description="Gifted Melody")
        await ReactionType.create(emoji="⚡", sentiment="like", score=2.0, description="Electrifying")
        await ReactionType.create(emoji="👍", sentiment="like", score=3.0, description="Solid Track / Approval")
        await ReactionType.create(emoji="👏", sentiment="like", score=1.0, description="Well Produced / Applause")
        await ReactionType.create(emoji="🧠", sentiment="like", score=1.0, description="Deep / Genius Lyrics")
        await ReactionType.create(emoji="🤝", sentiment="like", score=3.0, description="Relatable Vibe")
        await ReactionType.create(emoji="🍾", sentiment="like", score=5.0, description="Celebration Pop")
        await ReactionType.create(emoji="💋", sentiment="like", score=5.0, description="Seductive / Smooth Vibe")
        await ReactionType.create(emoji="🦄", sentiment="like", score=3.0, description="Unique / Magical Sound")
        await ReactionType.create(emoji="🕊️", sentiment="like", score=4.5, description="Peaceful / Chill Vibe")
        await ReactionType.create(emoji="💟", sentiment="like", score=4.5, description="Pleasant / Soft Vibe")
        await ReactionType.create(emoji="💵", sentiment="like", score=3.5, description="Rich Production Value")
        await ReactionType.create(emoji="👾", sentiment="like", score=2.0, description="Synthwave / Gaming Vibe")
        await ReactionType.create(emoji="🎈", sentiment="neutral", score=1.0, description="Lighthearted / Feel-good")
        await ReactionType.create(emoji="🍌", sentiment="dislike", score=-4.0, description="Fun / Quirky Track")
        await ReactionType.create(emoji="🍉", sentiment="neutral", score=0.0, description="Summer / Refreshing Vibe")
        await ReactionType.create(emoji="🍓", sentiment="like", score=3.0, description="Sweet / Acoustic Vibe")
        await ReactionType.create(emoji="🆒", sentiment="like", score=3.5, description="Trendy / Cool Track")
        await ReactionType.create(emoji="🐾", sentiment="neutral", score=1.0, description="Cute / Playful Beats")
        await ReactionType.create(emoji="💅", sentiment="like", score=3.5, description="Sassy / Confident Anthems")

        # --- HIGH ARTISTIC IMPACT / EMOTIONAL RESPONSES (MAPPED TO LIKE) ---
        await ReactionType.create(emoji="😭", sentiment="like", score=4.8, description="Deeply Moving / Beautifully Sad")
        await ReactionType.create(emoji="😱", sentiment="like", score=4.2,
                                  description="Mind-blowing Drop / Shocking Twist")
        await ReactionType.create(emoji="😢", sentiment="like", score=4.0,
                                  description="Melancholic / Nostalgic Melodies")
        await ReactionType.create(emoji="💔", sentiment="like", score=3.5, description="Heartbreak Anthem / Deep Lyrics")

        # --- MID-LEVEL ENGAGEMENT (NEUTRAL) ---
        await ReactionType.create(emoji="🤔", sentiment="neutral", score=-1.0, description="Experimental / Complex Music")
        await ReactionType.create(emoji="🧐", sentiment="neutral", score=-1.5,
                                  description="Analytical Listening / Complex Production")
        await ReactionType.create(emoji="😐", sentiment="neutral", score=-1.0, description="Unremarkable / Plain Track")
        await ReactionType.create(emoji="🤷", sentiment="dislike", score=-2.0, description="Indifferent / Not My Genre")
        await ReactionType.create(emoji="😮", sentiment="neutral", score=2.0, description="Surprising Element")
        await ReactionType.create(emoji="💬", sentiment="neutral", score=0.0, description="Talk-heavy / Podcast Vibe")
        await ReactionType.create(emoji="👀", sentiment="dislike", score=-2.0, description="Intriguing / Hidden Gem")
        await ReactionType.create(emoji="Ghost", sentiment="neutral", score=1.0, description="Eerie / Ambient Sounds")
        await ReactionType.create(emoji="👻", sentiment="like", score=2.5, description="Spooky / Electro-Goth Beat")
        await ReactionType.create(emoji="👨‍💻", sentiment="neutral", score=1.5,
                                  description="Lo-Fi / Focus / Coding Music")
        await ReactionType.create(emoji="🐱", sentiment="like", score=2.5, description="Whimsical / Cozy Track")
        await ReactionType.create(emoji="Dogs", sentiment="like", score=2.5, description="Upbeat / Background Noise")
        await ReactionType.create(emoji="🐶", sentiment="neutral", score=1.0, description="Friendly / Casual Listening")
        await ReactionType.create(emoji="🐰", sentiment="neutral", score=1.0, description="Bouncy / Fast-paced")
        await ReactionType.create(emoji="🦊", sentiment="neutral", score=1.5, description="Clever Remix / Slick Beats")
        await ReactionType.create(emoji="☃️", sentiment="like", score=3.5, description="Winter / Seasonal Vibe")
        await ReactionType.create(emoji="🎄", sentiment="like", score=3.5, description="Holiday / Festive Theme")
        await ReactionType.create(emoji="❤", sentiment="like", score=4.0, description="Standard Like")
        await ReactionType.create(emoji="❤‍🔥", sentiment="like", score=5.0, description="Warm Interest")
        await ReactionType.create(emoji="🤣", sentiment="like", score=2.0, description="Funny / Satirical Lyrics")
        await ReactionType.create(emoji="💘", sentiment="like", score=3.5, description="Catchy Love Song")
        await ReactionType.create(emoji="🕊", sentiment="like", score=4.0, description="Calm / Ambient Outro")
        await ReactionType.create(emoji="👌", sentiment="like", score=3.5, description="Decent / Acceptable Mix")
        await ReactionType.create(emoji="🤯", sentiment="like", score=5.0,
                                  description="Insane Production / Complex Drop")
        await ReactionType.create(emoji="💊", sentiment="neutral", score=2.0, description="Trippy / Psychedelic Sound")
        await ReactionType.create(emoji="🤷‍♂", sentiment="neutral", score=-1.5, description="Undecided Response")
        await ReactionType.create(emoji="🎅", sentiment="like", score=2.5, description="Christmas / Nostalgic Track")
        await ReactionType.create(emoji="🌚", sentiment="dislike", score=-3.0, description="Dark / Underground Vibe")
        await ReactionType.create(emoji="🫡", sentiment="neutral", score=2.0, description="Respect to a Classic Track")
        await ReactionType.create(emoji="🙏", sentiment="like", score=2.5, description="Soulful / Spiritual Melodies")
        await ReactionType.create(emoji="😍", sentiment="like", score=2.5, description="Highly Captivating Hook")
        await ReactionType.create(emoji="🐳", sentiment="neutral", score=-2.0, description="Deep / Low-Frequency Bass")

        # --- NEGATIVE SENTIMENTS / REJECTION (DISLIKE) ---
        await ReactionType.create(emoji="🥱", sentiment="dislike", score=-4.0, description="Boring / Derivative Track")
        await ReactionType.create(emoji="😴", sentiment="dislike", score=-3.5, description="Tiring / Low-energy Skater")
        await ReactionType.create(emoji="🙄", sentiment="dislike", score=-3.0, description="Annoying / Cliche Lyrics")
        await ReactionType.create(emoji="🤨", sentiment="dislike", score=-3.0, description="Off-key / Poorly Mixed")
        await ReactionType.create(emoji="😤", sentiment="dislike", score=-4.5, description="Aggravating / Bad Noise")
        await ReactionType.create(emoji="😡", sentiment="dislike", score=-4.0, description="Irritating Sonic Choices")
        await ReactionType.create(emoji="🤬", sentiment="dislike", score=-5.0, description="Unlistenable Noise")
        await ReactionType.create(emoji="👿", sentiment="like", score=4.0, description="Harsh / Malicious Frequency")
        await ReactionType.create(emoji="👎", sentiment="dislike", score=-4.0, description="Bad Track / Thumbs Down")
        await ReactionType.create(emoji="🚫", sentiment="neutral", score=-0.5,
                                  description="Skip Immediately / Do Not Recommend")
        await ReactionType.create(emoji="🙉", sentiment="dislike", score=-4.5,
                                  description="Terrible Audio / Ear Hurting")
        await ReactionType.create(emoji="🙈", sentiment="neutral", score=0.5,
                                  description="Bad Performance / Can't Watch")
        await ReactionType.create(emoji="🙊", sentiment="dislike", score=-4.0, description="Awful Vocals")
        await ReactionType.create(emoji="🥴", sentiment="dislike", score=-5.0, description="Disorienting / Awful Mix")
        await ReactionType.create(emoji="🤢", sentiment="dislike", score=-5.0, description="Repulsive Production")
        await ReactionType.create(emoji="🤮", sentiment="dislike", score=-5.0, description="Hated Everything About It")
        await ReactionType.create(emoji="💩", sentiment="dislike", score=-5.0,
                                  description="Garbage Quality / Worst Track")
        await ReactionType.create(emoji="🤡", sentiment="dislike", score=-5.0, description="Joke Track / Fake Artist")
        await ReactionType.create(emoji="🖕", sentiment="dislike", score=-5.0, description="Offensive / Total Rejection")

async def main():
    # Example usage workflow matching the update
    await ReactionType.seed_reaction_types()
    # rx = await ReactionType.get_by_emoji("🔥")
    # if rx:
    #     print("Sentiment:", await rx.get_parameter("sentiment"))
    #     print("Score:", await rx.get_parameter("score"))
    #     await rx.update_parameter("score", -5.0)
    #     print("Updated Score:", await rx.get_parameter("score"))


if __name__ == "__main__":
    asyncio.run(main())


# 1,❤️,like,5,Love / Deep Affection
# 2,👍,like,4,Thumbs Up / Solid Approval
# 3,🔥,like,4.5,Fire / Hype / Excellent Work
# 4,🥰,like,4.5,Smiling Face with Hearts / Adoration
# 5,👏,like,4,Clapping Hands / Congratulations
# 6,🎉,like,4,Party Popper / Celebration
# 7,🤩,like,4.5,Star-Struck / Amazing Contribution
# 8,😱,like,3,Screaming Face / Positive Shock or Wow Factor
# 9,🚀,like,4.5,Rocket / Growth / Exceptional Progress
# 10,💯,like,5,Hundred Points / Absolute Agreement
# 11,🕊️,like,3,Dove / Peace or Respectful Validation
# 12,💵,like,3.5,Dollar Banknote / Financial Success or High Value
# 13,👑,like,5,Crown / Top Tier / Respect for the Master
# 14,🧠,like,4,Brain / Genius Idea or Deep Thought
# 15,❤️‍🔥,like,4.5,Heart on Fire / Intensely Passionate Approval
# 16,👾,like,2.5,Alien Monster / Playful Geeky Appreciation
# 17,🏆,like,5,Trophy / Ultimate Achievement or Winning Track
# 18,⚡,like,4,High Voltage / Electric Energy or Speed
# 19,🎈,like,3,Balloon / Festive Joy
# 20,🤝,like,4,Handshake / Agreement and Cooperation
# 21,🍌,like,2,Banana / Quirky or Inside Joke Approval
# 22,🍉,like,2,"Watermelon / Pleasant, Chill Vibes"
# 23,💖,like,4.5,Sparkling Heart / Warm Appreciation
# 24,💞,like,4.5,Revolving Hearts / Shared Musical Synergy
# 25,💓,like,4,Beating Heart / Excitement
# 26,💗,like,4,Growing Heart / Deepening Validation
# 27,💝,like,4,Heart with Ribbon / Treating as a Gift
# 28,💟,like,3,Heart Decoration / Gentle Aesthetic Approval
# 29,🍓,like,2.5,"Strawberry / Sweet, Fresh Content"
# 30,💋,like,3.5,Kiss Mark / Bold Sign-off
# 31,🍾,like,4,Popping Champagne / Big Success Milestones
# 32,🆒,like,3,Squared Cool / Neat Layout or Cool Factor
# 33,🦄,like,4,Unicorn / Rare and Highly Unique Post
# 34,🐾,like,2,Paw Prints / Gentle or Cute Engagement
# 35,💅,like,3,Nail Polish / Sassy Excellence or Confidence
# 36,🤔,neutral,0,Thinking Face / Evaluating or Skeptical
# 37,🧐,neutral,0,Face with Monocle / Critical Analysis
# 38,😐,neutral,-0.5,Neutral Face / Unmoved or Speechless
# 39,🤷,neutral,0,Person Shrugging / Indifference or Uncertainty
# 40,😮,neutral,0.5,Face with Open Mouth / Mild Surprise
# 41,💬,neutral,0,Speech Balloon / Prompting Discussion
# 42,👀,neutral,0.5,Eyes / Watching closely or Curious Tracking
# 43,Ghost,neutral,0.5,"Ghost / Playful, Spooky, or Silly Vibe"
# 44,👻,neutral,0.5,Ghost / Playful or Silly Context
# 45,👨‍💻,neutral,0.5,Man Technologist / Coding or Behind-the-Scenes Build
# 46,🐱,neutral,1,Cat Face / Innocent Cuteness
# 47,Dogs,neutral,1,Dog Face / Friendly acknowledgement
# 48,🐶,neutral,1,Dog Face / Friendly Context
# 49,🐰,neutral,1,Rabbit Face / Soft Engagement
# 50,🦊,neutral,0.5,Fox / Clever or Slick Reference
# 51,☃️,neutral,0.5,Snowman / Chilling Out or Winter Vibe
# 52,🎄,neutral,0.5,Christmas Tree / Seasonal Vibe
# 53,👎,dislike,-4,Thumbs Down / Clear Disapproval
# 54,🤮,dislike,-5,Face Vomiting / Absolute Disgust or Trash Content
# 55,🤢,dislike,-4,Nauseated Face / Heavy Repulsion or Cringe
# 56,💩,dislike,-5,Pile of Poop / Pure Garbage Quality
# 57,🤡,dislike,-5,Clown Face / Mocking a Foolish Stance
# 58,🖕,dislike,-5,Middle Finger / Aggressive Hostility and Insult
# 59,🤬,dislike,-4.5,Face with Symbols on Mouth / Furious Toxic Rage
# 60,😤,dislike,-3,Face with Steam From Nose / Arrogant Pushback or Frustration
# 61,😡,dislike,-4,Pouting Face / Direct Anger
# 62,😭,dislike,-2,Loudly Crying Face / Overwhelmed Grief or Sad News
# 63,😢,dislike,-2,Crying Face / Soft Disappointment
# 64,🥱,dislike,-3,Yawning Face / Boring or Uninspired Content
# 65,😴,dislike,-3,Sleeping Face / Puts Audience to Sleep
# 66,🙄,dislike,-3,Face with Rolling Eyes / Dismissive Sarcasm or Annoyance
# 67,🥴,dislike,-2,Woozy Face / Highly Confused or Uncomfortable
# 68,🙉,dislike,-2.5,Hear-No-Evil Monkey / Blocking Out Painful Cringe or Spoilers
# 69,🙈,dislike,-1.5,See-No-Evil Monkey / Second-Hand Embarrassment
# 70,🙊,dislike,-2,Speak-No-Evil Monkey / Quiet Judgment or Speechless Dislike
# 71,🚫,dislike,-4,Prohibited / Violation of Group Guidelines
# 72,🤨,dislike,-2,Face with Raised Eyebrow / Highly Suspicious Claim
# 73,👿,dislike,-3.5,Angry Face with Horns / Malicious Intent or Spiteful Reaction
# 74,💔,like,4.5,Broken Heart / Heavy Emotional Damage or Hurt
# 75,❤,neutral,0,
# 76,❤‍🔥,neutral,0,
# 77,🤣,neutral,0,
# 78,💘,neutral,0,
# 79,🕊,neutral,0,
# 80,👌,neutral,0,
# 81,🤯,neutral,0,
# 82,💊,neutral,0,
# 83,🤷‍♂,neutral,0,
# 84,🎅,neutral,0,
# 85,🌚,neutral,0,
# 86,🫡,neutral,0,
# 87,🙏,neutral,0,
# 88,😍,neutral,0,
# 89,🐳,neutral,0,
