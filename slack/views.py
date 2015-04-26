from bot import SlackBot
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from slack.models import SlackUser
import cleverbot
import json
import re

INFO_URL = "https://www.changetip.com/tip-online/slack"
MESSAGES = {
    "help": """Hi {user_name}. Here's some help.
To send a tip, mention *a person* and *an amount* like this:
`changetip: give @buddy $1`.
You can also use a moniker for the amount, like `a beer` or `2 coffees`.
Any questions? E-mail support@changetip.com
""",
    "duplicate": "That looks like a duplicate tip.",
    "greeting": "Nice to meet you, {user_name}! {get_started}",
    "get_started": "To send your first tip, login with your slack account on ChangeTip: {info_url}".format(info_url=INFO_URL),
    "unknown_receiver": "@{user_name}, I don't know who that person is yet. They should say *hi* to me before I give them money.",
    "out_for_delivery": "The tip for {amount_display} is out for delivery. {receiver} needs to collect by connecting their ChangeTip account to slack at %s" % INFO_URL,
    "finished": "The tip has been delivered, {amount_display} has been added to {receiver}'s ChangeTip wallet."
}


@require_POST
def command_webhook(request):
    """
    Handle data from a webhook
    """
    print(json.dumps(request.POST.copy(), indent=2))
    # Do we have this user?
    user_name = request.POST.get("user_name")
    slack_sender, created = SlackUser.objects.get_or_create(
        name=user_name,
        team_id=request.POST.get("team_id"),
        user_id=request.POST.get("user_id"),
    )
    if created:
        return JsonResponse({"text": MESSAGES["greeting"].format(user_name=user_name, get_started=MESSAGES["get_started"])})

    text = request.POST.get("text", "")

    # Check for mention in the format of <@$userid>
    mention_match = re.search('<@(U[A-Z0-9]+)>', text)
    if not mention_match:
        # Do they want help?
        if "help" in text:
            return JsonResponse({"text": MESSAGES["help"].format(user_name=user_name)})
        else:
            # Say something clever
            cb = cleverbot.Cleverbot()
            response = cb.ask(text.replace('changetip', ''))
            return JsonResponse({"text": response, "username": "changetip-cleverbot"})

    slack_receiver = SlackUser.objects.filter(team_id = slack_sender.team_id, user_id=mention_match.group(1)).first()
    if not slack_receiver:
        return JsonResponse({"text": MESSAGES["unknown_receiver"].format(user_name=user_name)})

    # Substitute the @username back in
    text = text.replace(mention_match.group(0), '@%s' % slack_receiver.name)

    # Submit the tip
    bot = SlackBot()
    team_domain = request.POST.get("team_domain")
    tip_data = {
        "sender": "%s@%s" % (slack_sender.name, team_domain),
        "receiver": "%s@%s" % (slack_receiver.name, team_domain),
        "message": text,
        "context_uid": bot.unique_id(request.POST.copy()),
        "meta": {}
    }
    for meta_field in ["token", "team_id", "channel_id", "channel_name", "user_id", "user_name", "command"]:
        tip_data["meta"][meta_field] = request.POST.get(meta_field)

    if request.POST.get("noop"):
        return JsonResponse({"text": "Hi!"})

    response = bot.send_tip(**tip_data)
    out = ""
    if response.get("error_code") == "invalid_sender":
        out = MESSAGES["get_started"]
    elif response.get("error_code") == "duplicate_context_uid":
        out = MESSAGES["duplicate"]
    elif response.get("error_message"):
        out = response.get("error_message")
    elif response.get("state") in ["ok", "accepted"]:
        tip = response["tip"]
        if tip["status"] == "out for delivery":
            out += MESSAGES["out_for_delivery"].format(amount_display=tip["amount_display"], receiver=tip["receiver"])
        elif tip["status"] == "finished":
            out += MESSAGES["finished"].format(amount_display=tip["amount_display"], receiver=tip["receiver"])

    if "+debug" in text:
        out += "\n```\n%s\n```" % json.dumps(response, indent=2)

    return JsonResponse({"text": out})


def home(request):
    return HttpResponse("OK")
