"""Musical identity of the three departments. Only these genres exist in the system."""

DEPARTMENTS = {
    "reggae": {
        "label": "Reggae Storytelling",
        "subgenres": {
            "roots reggae": {"bpm": (68, 80), "palette": [
                "one drop drums, deep round bass, offbeat skank guitar, organ bubble, warm horn section",
                "steppers kick, dub-style bass, nyabinghi hand drums, skank guitar, melodica",
                "one drop drums, heavy bass, clean rhythm guitar, Hammond organ, trombone and trumpet"]},
            "conscious reggae": {"bpm": (70, 84), "palette": [
                "one drop drums, rolling bassline, skank guitar, piano chops, brass stabs",
                "rockers drum pattern, deep bass, wah guitar licks, organ bubble, harmonica"]},
            "lovers rock": {"bpm": (66, 78), "palette": [
                "soft one drop, warm melodic bass, clean electric piano, gentle strings, light guitar",
                "lovers rock groove, round bass, Rhodes piano, soft backing harmonies, sax"]},
        },
        "vocal": ["warm male baritone, soulful, relaxed reggae phrasing",
                  "male tenor lead, heartfelt, conversational reggae delivery",
                  "deep male voice, storytelling tone, gentle vibrato"],
        "harmony": "male and female backing harmonies on the chorus",
        "themes": [
            "a father teaching his son to stand tall after losing his job",
            "two friends who chose different roads — one hustle, one school",
            "a mother selling vegetables at dawn to pay school fees",
            "forgiving someone who broke your trust",
            "leaving the village for the city and missing home",
            "a heartbreak that taught patience",
            "rent is due and the cupboard is empty but hope remains",
            "a young man resisting easy money from the wrong crowd",
            "rebuilding life after a fire took everything",
            "staying faithful to a love across long distance",
            "the wisdom of grandparents on a porch at sunset",
            "standing up for a neighbour who is treated unfairly",
            "a farmer waiting for rain",
            "learning to love yourself after years of doubt",
            "the day a long friendship ended over money",
            "gratitude for small things when life is hard",
            "a soldier coming home to a changed family",
            "a street vendor's dignity",
            "rising from a mistake and making it right",
            "a lover's promise made under the mango tree",
        ],
    },
    "afrobeats": {
        "label": "Afrobeats & Amapiano Storytelling",
        "subgenres": {
            "afrobeats": {"bpm": (98, 110), "palette": [
                "afrobeats groove, syncopated percussion, shakers, talking drum, warm bass, highlife guitar",
                "afro-pop drums, crisp snare, layered congas, plucked guitar riff, soft synth pads",
                "afrobeats rhythm, kick and rim pattern, shekere, melodic bass, horn riff"]},
            "amapiano": {"bpm": (110, 116), "palette": [
                "amapiano log drum bass, shakers, jazzy piano chords, airy pads, soft kicks",
                "amapiano groove, deep log drum, rimshots, soulful Rhodes, flute melody",
                "private school amapiano, smooth log drum, saxophone lines, warm keys"]},
        },
        "vocal": ["smooth male tenor, melodic afrobeats phrasing, light ad-libs",
                  "male vocal, warm and confident, call-and-response hooks",
                  "male lead, laid-back amapiano delivery, soulful runs"],
        "harmony": "layered male backing vocals and group chants on the hook",
        "themes": [
            "first salary and the people who believed in you",
            "a love that started at a wedding dance floor",
            "hustling in the city with big dreams and small money",
            "a girl who supported you before the success",
            "Friday night after a hard week — celebration with friends",
            "making your mother proud",
            "a long-distance love on video calls",
            "starting a small business from nothing",
            "jealousy breaking a relationship and learning to trust",
            "graduation day after many struggles",
            "the market queen who runs the neighbourhood",
            "dancing to forget the stress of the week",
            "a promise to marry when the money comes",
            "returning home in December to family",
            "a friend who disappeared when fame came",
            "chasing a dream against everyone's advice",
            "first date on the back of a motorbike taxi",
            "a love song for a woman who works night shifts",
            "community block party under the stars",
            "learning to save money after wasting it",
        ],
    },
    "relaxation": {
        "label": "Relaxation",
        "subgenres": {
            "study": {"bpm": (60, 76), "palette": [
                "instrumental, soft felt piano, warm pads, gentle brushes, light tape warmth",
                "instrumental, mellow electric piano, soft bass, subtle vinyl texture, calm"]},
            "sleep": {"bpm": (50, 62), "palette": [
                "instrumental, slow ambient piano, long reverb, soft string pads, no drums",
                "instrumental, drifting synth pads, distant piano notes, deep calm"]},
            "meditation": {"bpm": (50, 66), "palette": [
                "instrumental, kalimba, soft drones, wooden flute, gentle rain ambience",
                "instrumental, mbira patterns, warm pad, soft hand percussion, peaceful"]},
            "calm piano": {"bpm": (58, 72), "palette": [
                "instrumental, solo grand piano, intimate, expressive dynamics, warm room",
                "instrumental, piano and cello duet, slow and tender"]},
        },
        "vocal": [],
        "harmony": "",
        "themes": ["sunrise over Lake Kivu", "quiet library afternoon", "rain on a tin roof", "night train",
                   "tea garden mist", "deep breathing", "ocean at dusk", "candlelight", "mountain silence",
                   "slow river", "starry savanna night", "early morning study", "garden after rain",
                   "soft focus", "floating clouds", "evening calm"],
    },
}

KEYS = ["C major", "G major", "D major", "A major", "E major", "F major", "Bb major", "Eb major", "Ab major",
        "A minor", "E minor", "B minor", "D minor", "G minor", "C minor", "F# minor", "C# minor"]

SETTINGS_PLACES = ["Kigali", "Lagos", "Accra", "Nairobi", "Kampala", "Johannesburg", "Dar es Salaam",
                   "Kingston", "a small village", "a busy taxi park", "a hillside town", "a coastal town",
                   "a crowded market", "a quiet farm"]

PERSPECTIVES = ["first person, singer living it", "first person, looking back years later",
                "second person, advice to a younger self", "third person, telling a neighbour's story",
                "a conversation between two people"]

ARCS = ["struggle to hope", "joy with a bittersweet twist", "regret to redemption",
        "doubt to confidence", "loss to gratitude", "temptation to wisdom", "longing to reunion"]
