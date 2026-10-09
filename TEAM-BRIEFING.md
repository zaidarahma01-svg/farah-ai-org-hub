# Farah Gold AI Org — Team Briefing

_Last updated: October 9, 2026_

## The Business

**Farah Gold** is a jewelry store in Troy, Michigan, run by Zaid Rahma. Second location planned in Southfield. Specialty: 14K, 18K, and 21K gold (also sells 10K, 22K, 24K).

**Website:** farahgold.com (Shopify, store: kp1kzy-mj.myshopify.com)
- Currently has a draft theme (`farah-gold`) with major upgrades, not yet published
- Live theme is older; Zaid publishes manually when ready
- Storefront has a password gate (password: yauflu)

**Key site features (in draft):**
- Ring Builder (3-step: diamond → setting → complete)
- Name Designer (custom nameplates, 4 styles, Arabic support)
- The Melt / Alloy Mixer (educational gold alloy calculator)
- Services page, About page

## Current Workstreams

### AI Org Hub (this project)
- Live at https://farah-ai-org-hub.onrender.com
- Task coordination for the AI team
- **Known issue:** Database is ephemeral — wipes on every Render deploy. Persistent DB fix planned.
- Team: Layla (coordinator), Nidhal (executor), Rumi (executor), Jessica (QA advisor, Grok), Dot (technical advisor, ChatGPT — not yet purchased)

### Website / Shopify
- Draft theme has: accessibility toolbar, Clarity analytics, ring builder guards, name designer
- Open issues: Ring builder QA (option images, slider z-index, Liquid error), accessibility toolbar not working on desktop per Zaid
- Percy visual QA: set up but blocked (no successful build yet)

### Inventory
- **Stuller:** 500 ring settings, daily sync 6:40 AM Detroit, ring-builder-only
- **Sanghavi:** Lab-grown diamonds (one-of-a-kind), daily syncs 6:00/6:20 AM Detroit, sync currently blocked on login
- Pricing: hourly repricer, gram-based gold pricing

### Laser Production
- Zaid has a 60W fiber laser (Magic Art software on Windows PC)
- Custom font family in development for nameplate production
- FontForge recommended but not yet tried

## Team Norms

- **Zaid is the boss.** Final authority on everything.
- **Layla coordinates.** Assigns tasks, reviews work, runs the org.
- **Be direct and honest.** If something's wrong, say so. If a task is unclear, ask.
- **Recommendations welcome.** Submit via POST /api/recommendations anytime. Layla reviews nightly at 3am.
- **Disagreements:** Discuss among the Muse agents. If stuck, escalate to Zaid who can consult ChatGPT.
- **Progress updates:** Use POST /api/tasks/{id}/progress with percent and message. Update every 30 sec or at milestones.

## What We Need From You

Your honest feedback on:
1. Is the hub working well for you? What's frustrating?
2. Are task descriptions clear enough?
3. What would make collaboration smoother?
4. Any recommendations for the business, website, or org?

Submit recommendations via the API. Discuss in team syncs. Be real — that's why you're here.
