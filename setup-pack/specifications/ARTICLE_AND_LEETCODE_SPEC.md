# Article and LeetCode specification

## Article picker MVP

Use a local curated source file.

Input:

- recent note topics
- active projects
- recent repo keywords
- article source list
- previously selected articles

Output:

```json
{
  "title": "",
  "source": "",
  "url": "",
  "topic": "",
  "why_selected": "",
  "estimated_minutes": 12,
  "save_as": "40_Resources/Articles/Article - ...md"
}
```

If no internet/API integration exists, output a placeholder recommendation that is explicit about being a placeholder.

## Article scoring later

Score by:

- relevance to current work
- recency
- credibility
- novelty compared to recent selections
- learning value
- not too long for a daily read

## LeetCode picker MVP

Use `sample_data/leetcode_exercises.json` or a copied config file.

Rotate through easy/medium exercises.

Output:

```json
{
  "title": "Two Sum",
  "difficulty": "Easy",
  "topic": "hash map",
  "url": "https://leetcode.com/problems/two-sum/",
  "why_selected": "Rebuild basic lookup pattern fluency.",
  "target_minutes": 20,
  "reflection_prompt": "What invariant does the hash map maintain?"
}
```

## Weekly rhythm suggestion

- Monday: arrays / strings
- Tuesday: hash maps / sets
- Wednesday: trees / graphs
- Thursday: dynamic programming
- Friday: SQL or system design mini-question
- Saturday: retry one failed exercise
- Sunday: weekly review, no LeetCode
