# Music-generation research (Phase 1)

| Provider | Male vocals | Instrumentals | African / Amapiano / Reggae | API | Hardware | Licence | Commercial use | Verdict |
|---|---|---|---|---|---|---|---|---|
| **ACE-Step 1.5** | Yes, sings supplied lyrics; between Suno v4.5 and v5 per its paper | Yes | Prompt-driven: Afrobeats fair–good, Amapiano partial, Reggae good | Python (diffusers), REST, Gradio | NVIDIA GPU, < 4 GB VRAM offloaded; Kaggle T4/P100 OK | MIT | Allowed | **Selected** |
| MusicGen (AudioCraft) | No | Yes (≤ 30 s native) | Weak | Python | GPU | Code MIT, **weights CC-BY-NC** | **No** | Rejected |
| YuE | Yes | Yes | Fair | Python | 24 GB+ GPU | Apache-2.0 | Allowed | Too heavy for free GPUs |
| Stable Audio Open | No | Short (≤ 47 s) | Weak | Python | GPU | Stability Community Licence | Conditional | Rejected (no vocals) |
| Suno free tier | Yes | Yes | Good | No official API | — | Suno ToS | **No** (non-commercial; Suno owns free-tier output) | Excluded |

Notes
- AI-generated audio may have limited or no copyright protection in some countries; the lyrics you
  review/edit and the overall work may still be protectable. This is not legal advice.
- ACE-Step's developers state their training data is licensed, royalty-free or synthetic.
- Adding a provider: subclass `nikoblaze.music.base.Provider` (`submit`, `poll`, `fetch`) and register it
  in `get_provider()`. Takes must come back as 24-bit WAV + optional word timings.
- Future quality upgrade (still free): a LoRA fine-tuned on Niko Blaze's own approved vocals would give a
  consistent signature voice. Only train on audio you own.
