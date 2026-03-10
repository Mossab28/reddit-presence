import os
import anthropic


def generate_reply(post_title, post_body, subreddit, matched_keywords):
    """Generate a contextual, helpful reply using Claude."""
    company_name = os.getenv("COMPANY_NAME", "our company")
    company_desc = os.getenv("COMPANY_DESCRIPTION", "")
    company_url = os.getenv("COMPANY_URL", "")

    prompt = f"""You are a knowledgeable tech professional who genuinely helps people on Reddit.
You work at {company_name}, which {company_desc}.

Write a helpful reply to this Reddit post from r/{subreddit}.

POST TITLE: {post_title}

POST BODY:
{post_body[:3000]}

MATCHED KEYWORDS: {', '.join(matched_keywords)}

RULES:
- Be genuinely helpful first. Answer the question or provide useful advice.
- Write in a natural, conversational Reddit tone. No corporate speak.
- Only mention {company_name} if it is directly relevant to solving the user's problem.
- If you mention the company, do it briefly and naturally (e.g., "I've had good results with X" or "at {company_name} we handle this by...").
- Do NOT include links unless the company solution is clearly the best answer.
- Keep it concise (2-4 paragraphs max).
- Do NOT start with "Great question!" or similar filler.
- Do NOT use markdown headers.
- Sound like a real person, not a bot.
"""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
