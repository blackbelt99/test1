# ╔══════════════════════════════════════════════════════════════╗
# ║         ZYPHERNODE BOT — Python Edition (discord.py)      ║
# ║  Tickets · Timeout · AFK · Invites · Moderation · Utility   ║
# ╚══════════════════════════════════════════════════════════════╝

import discord
from discord.ext import commands
from discord import app_commands
import os, re, asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────────────────
def _int_env(key):
    val = os.getenv(key, "").strip()
    try:
        return int(val) if val and val.isdigit() else 0
    except:
        return 0

TOKEN               = os.getenv("BOT_TOKEN", "").strip()
BOT_NAME            = os.getenv("BOT_NAME", "ZypherNode").strip()
STREAM_URL          = os.getenv("STREAM_URL", "https://twitch.tv/zyphernode").strip()
TICKET_CATEGORY_ID  = _int_env("TICKET_CATEGORY_ID")
TICKET_LOG_ID       = _int_env("TICKET_LOG_CHANNEL_ID")
MOD_LOG_ID          = _int_env("MOD_LOG_CHANNEL")
BOT_LOG_ID          = _int_env("BOT_LOG_CHANNEL")
INVITE_LOG_ID       = _int_env("INVITE_LOG_CHANNEL")
SUPPORT_ROLE_ID     = _int_env("SUPPORT_ROLE_ID")
TICKET_COOLDOWN_S   = 300  # 5 minutes
FAKE_DAYS           = 30   # accounts newer than this = fake (change with $setfakedays)
TICKET_PING_ROLE_ID = 0  # set with $ticket setping or Set Ping Role button
TICKET_CLOSE_DM = "Your ticket **{ticket_name}** has been closed by **{closer}**. Thank you for contacting us! If you have any further questions, feel free to open a new ticket."

# ─── Colors ──────────────────────────────────────────────────────────────────
C_PRIMARY = discord.Color.blurple()
C_SUCCESS = discord.Color.green()
C_ERROR   = discord.Color.red()
C_WARN    = discord.Color.yellow()
C_INFO    = discord.Color.blue()
C_TICKET  = discord.Color.from_str("#eb459e")
C_AFK     = discord.Color.purple()
C_INVITE  = discord.Color.teal()

# ─── In-Memory Stores ────────────────────────────────────────────────────────
afk_map        = {}   # user_id → {"reason": str, "time": datetime}
invite_cache   = {}   # guild_id → {code: uses}
invite_tracker = defaultdict(lambda: defaultdict(lambda: {"invites": 0, "left": 0, "fake": 0, "rejoins": 0}))
member_inviter  = {}   # (guild_id, member_id) → inviter_id
member_type     = {}   # (guild_id, member_id) → "real"|"fake"|"rejoin"
warn_map       = defaultdict(list)   # (guild_id, user_id) → [{"reason","mod","time"}]
note_map       = defaultdict(list)   # (guild_id, user_id) → [{"text","mod","time"}]
ticket_cd      = {}   # user_id → datetime

# ─── Bot Setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_duration(s: str):
    """Parse '10m', '2h', '1d' → timedelta or None"""
    m = re.fullmatch(r"(\d+)(s|m|h|d|w)", s.lower())
    if not m: return None
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{"s": {"seconds": n}, "m": {"minutes": n},
                        "h": {"hours": n}, "d": {"days": n}, "w": {"weeks": n}}[unit])

def fmt_delta(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 60:   return f"{total}s"
    if total < 3600: return f"{total//60}m"
    if total < 86400:return f"{total//3600}h"
    return f"{total//86400}d"

def time_ago(dt: datetime) -> str:
    diff = datetime.now(timezone.utc) - dt
    s = int(diff.total_seconds())
    if s < 60:   return f"{s}s ago"
    if s < 3600: return f"{s//60}m ago"
    if s < 86400:return f"{s//3600}h ago"
    return f"{s//86400}d ago"

def ok_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"✅  {msg}", color=0x57f287)

def info_embed(title: str, msg: str) -> discord.Embed:
    e = discord.Embed(title=title, description=msg, color=0x5865f2)
    return e

def err_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"❌  {msg}", color=C_ERROR)

async def send_mod_log(guild, action, target, target_id, mod, reason, color=None):
    if not MOD_LOG_ID: return
    ch = guild.get_channel(MOD_LOG_ID)
    if not ch: return
    e = discord.Embed(title=f"📋 {action}", color=color or C_WARN, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Target",     value=f"{target} ({target_id})", inline=True)
    e.add_field(name="🛡️ Moderator", value=str(mod),                  inline=True)
    e.add_field(name="📝 Reason",     value=reason or "No reason",    inline=False)
    e.set_footer(text=f"ID: {target_id} • Made by Black Belt")
    await ch.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#  TICKET VIEWS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Ticket Setup Modals ───────────────────────────────────────────────────────
class TitleDescModal(discord.ui.Modal, title="Edit Title & Description"):
    panel_title = discord.ui.TextInput(
        label="Panel Title",
        placeholder=f"{BOT_NAME} — Support Ticket",
        max_length=100
    )
    panel_desc = discord.ui.TextInput(
        label="Panel Description",
        style=discord.TextStyle.paragraph,
        placeholder="Describe when to open a ticket...",
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        PANEL_CONFIG["title"]       = self.panel_title.value
        PANEL_CONFIG["description"] = self.panel_desc.value
        await interaction.response.send_message(
            embed=ok_embed(f"Title & Description updated!\nRun `$ticket panel` to resend."),
            ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(embed=err_embed(f"Error: {error}"), ephemeral=True)
        except:
            pass


class RulesModal(discord.ui.Modal, title="Edit Rules"):
    rules_text = discord.ui.TextInput(
        label="Rules (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Be patient\nNo spam\nRespect staff",
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        lines = [r.strip() for r in self.rules_text.value.splitlines() if r.strip()]
        PANEL_CONFIG["rules"] = lines
        await interaction.response.send_message(
            embed=ok_embed(f"{len(lines)} rules saved!\nRun `$ticket panel` to resend."),
            ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(embed=err_embed(f"Error: {error}"), ephemeral=True)
        except:
            pass


class HoursFooterModal(discord.ui.Modal, title="Edit Hours & Footer"):
    hours = discord.ui.TextInput(
        label="Support Hours",
        placeholder="11:30 AM to 11:30 PM",
        max_length=100
    )
    footer = discord.ui.TextInput(
        label="Footer Text",
        placeholder="ZypherNode | zyphernode.net",
        max_length=80,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        PANEL_CONFIG["support_hours"] = self.hours.value
        if self.footer.value:
            PANEL_CONFIG["footer"] = self.footer.value
        await interaction.response.send_message(
            embed=ok_embed(f"Hours & Footer updated!\nRun `$ticket panel` to resend."),
            ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(embed=err_embed(f"Error: {error}"), ephemeral=True)
        except:
            pass


class TicketSetupModal(discord.ui.Modal, title="Ticket Panel Setup"):
    """Legacy - kept for compatibility"""
    panel_title = discord.ui.TextInput(label="Panel Title", max_length=100)
    panel_desc  = discord.ui.TextInput(label="Description", style=2, max_length=800)

    async def on_submit(self, interaction: discord.Interaction):
        PANEL_CONFIG["title"]       = self.panel_title.value
        PANEL_CONFIG["description"] = self.panel_desc.value
        await interaction.response.send_message(
            embed=ok_embed("Panel updated! Run `$ticket panel` to resend."), ephemeral=True)


# ── Set Category Modal ────────────────────────────────────────────────────────
class SetCategoryModal(discord.ui.Modal, title="Set Ticket Category"):
    ticket_type = discord.ui.TextInput(
        label="Ticket Type (e.g. buy, partnership, support)",
        placeholder="buy",
        max_length=30
    )
    category_id = discord.ui.TextInput(
        label="Discord Category ID",
        placeholder="Right-click category → Copy ID",
        max_length=30
    )

    async def on_submit(self, interaction: discord.Interaction):
        key = self.ticket_type.value.strip().lower().replace(" ", "_")
        if key not in TICKET_CATEGORIES:
            cats = ", ".join(TICKET_CATEGORIES.keys())
            return await interaction.response.send_message(
                embed=err_embed(f"Type `{key}` not found.\nAvailable: {cats}"), ephemeral=True)
        try:
            cat_id = int(self.category_id.value.strip())
            cat = interaction.guild.get_channel(cat_id)
            if not cat or not isinstance(cat, discord.CategoryChannel):
                return await interaction.response.send_message(
                    embed=err_embed("Category not found. Make sure the ID is correct."), ephemeral=True)
            TICKET_CATEGORY_MAP[key] = cat_id
            emoji, label, _ = TICKET_CATEGORIES[key]
            await interaction.response.send_message(
                embed=ok_embed(f"**{emoji} {label}** tickets → **{cat.name}**"), ephemeral=True)
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Invalid ID. Enter a valid Category ID."), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(embed=err_embed(f"Error: {error}"), ephemeral=True)
        except:
            pass


# ── Ping Role Modal ───────────────────────────────────────────────────────────
class PingRoleModal(discord.ui.Modal, title="Set Ping Role"):
    role_input = discord.ui.TextInput(
        label="Role name, @mention, or ID",
        placeholder="e.g. Staff  or  @Staff  or  123456789",
        max_length=100,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        global TICKET_PING_ROLE_ID
        val = self.role_input.value.strip()
        if not val:
            TICKET_PING_ROLE_ID = 0
            await interaction.response.send_message(embed=ok_embed("Ping role removed."), ephemeral=True)
            return

        # Try to find role by mention, ID, or name
        import re
        role = None

        # Check if it's a mention like <@&123>
        mention_match = re.match(r"<@&(\d+)>", val)
        if mention_match:
            role = interaction.guild.get_role(int(mention_match.group(1)))

        # Check if it's a plain ID
        if not role and val.isdigit():
            role = interaction.guild.get_role(int(val))

        # Search by name (case insensitive)
        if not role:
            val_clean = val.lstrip("@")
            role = discord.utils.find(lambda r: r.name.lower() == val_clean.lower(), interaction.guild.roles)

        if not role:
            # List available roles
            role_list = ", ".join(f"`{r.name}`" for r in interaction.guild.roles if not r.is_default())
            return await interaction.response.send_message(
                embed=err_embed(f"Role not found: `{val}`\n\nAvailable roles:\n{role_list[:500]}"),
                ephemeral=True)

        TICKET_PING_ROLE_ID = role.id
        await interaction.response.send_message(
            embed=ok_embed(f"Ping role set to {role.mention}\nThis role will be pinged when a ticket is created."),
            ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(embed=err_embed(f"Error: {error}"), ephemeral=True)
        except:
            pass


# ── Setup Panel View (buttons) ─────────────────────────────────────────────────
class TicketSetupView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=None)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=err_embed("Only the person who ran this command can use these buttons."),
                ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Edit Title & Desc", style=discord.ButtonStyle.primary, row=0)
    async def edit_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TitleDescModal()
        modal.panel_title.default = PANEL_CONFIG.get("title", "")
        modal.panel_desc.default = PANEL_CONFIG.get("description", "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Rules", style=discord.ButtonStyle.primary, row=0)
    async def edit_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RulesModal()
        modal.rules_text.default = "\n".join(PANEL_CONFIG.get("rules", []))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Hours & Footer", style=discord.ButtonStyle.secondary, row=1)
    async def edit_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = HoursFooterModal()
        modal.hours.default = PANEL_CONFIG.get("support_hours", "")
        modal.footer.default = PANEL_CONFIG.get("footer", "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Preview Panel", style=discord.ButtonStyle.success, row=1)
    async def preview_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = build_panel_embed(interaction.guild)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Set Ping Role", style=discord.ButtonStyle.secondary, row=2)
    async def set_ping(self, interaction: discord.Interaction, button: discord.ui.Button):
        ask_msg = await interaction.channel.send(
            f"{interaction.user.mention} 👋 Please **mention the role** you want to ping on ticket create.\nExample: `@Staff`\n-# This message will auto-delete in 30 seconds."
        )
        await interaction.response.send_message(embed=ok_embed("Please mention the role in chat!"), ephemeral=True)

        def check(m):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id and len(m.role_mentions) > 0

        try:
            msg = await bot.wait_for("message", check=check, timeout=30.0)
            role = msg.role_mentions[0]
            global TICKET_PING_ROLE_ID
            TICKET_PING_ROLE_ID = role.id
            await msg.delete()
            await ask_msg.delete()
            confirm = await interaction.channel.send(embed=ok_embed(f"Ping role set to {role.mention} ✅"), delete_after=5)
        except:
            await ask_msg.delete()

    @discord.ui.button(label="Set Category", style=discord.ButtonStyle.secondary, row=2)
    async def set_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SetCategoryModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Send Panel Here", style=discord.ButtonStyle.danger, row=3)
    async def send_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(embed=build_panel_embed(interaction.guild), view=TicketOpenView())
        await interaction.response.send_message(embed=ok_embed("Ticket panel sent!"), ephemeral=True)


# ── Ticket Categories (customize freely) ──────────────────────────────────────
TICKET_CATEGORIES = {
    "create":      ("🤝", "Create Ticket",       "Click on this option to create a ticket"),
    "buy":         ("💰", "Buy/Purchase",         "Click on this option to create a ticket"),
    "rewards":     ("🎁", "Claim Rewards",        "Click on this option to create a ticket"),
    "partnership": ("🤝", "Ask For Partnership",  "Click on this option to create a ticket"),
    "support":     ("🎫", "Support Ticket",       "Click on this option to create a ticket"),
    "appeal":      ("⚖️", "Ban Appeal",           "Click on this option to create a ticket"),
    "other":       ("📋", "Other",                "Click on this option to create a ticket"),
}

# ── Per-category Discord category mapping: ticket_key → discord_category_id ────
TICKET_CATEGORY_MAP = {}  # e.g. {"buy": 123456789, "partnership": 987654321}

# ── Panel config (editable via -ticket setup) ──────────────────────────────────
PANEL_CONFIG = {
    "title":       f"{BOT_NAME} — Support Ticket",
    "description": (
        "Select one of the options below if you need help, want to buy "
        "Minecraft hosting, or have any questions. Only open a ticket if necessary. "
        "Making tickets for fun or time-pass may result in a blacklist from ticket creation."
    ),
    "rules": [
        "🔴 Please be patient — our staff will assist you soon.",
        "✅ Answering questions is mandatory.",
        "🙏 Be respectful to moderators. All conversations are recorded.",
    ],
    "support_hours": "11:30 AM to 11:30 PM",
    "footer":        "ZypherNode | zyphernode.net",
    "color":         0x5865f2,
}

class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key, emoji=emoji, description=desc)
            for key, (emoji, label, desc) in TICKET_CATEGORIES.items()
        ]
        super().__init__(placeholder="🎫 Select a topic...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        key = self.values[0]
        emoji, label, desc = TICKET_CATEGORIES[key]
        guild = interaction.guild
        user  = interaction.user



        # Duplicate check — per category (user can have one ticket per category)
        safe_name = re.sub(r"[^a-z0-9]", "", user.name.lower())[:16]
        existing = discord.utils.find(
            lambda c: c.name.startswith(f"ticket-{safe_name}-{key}") and
                      c.topic and str(user.id) in c.topic,
            guild.text_channels)
        if existing:
            return await interaction.followup.send(
                embed=err_embed(f"You already have an open **{label}** ticket: {existing.mention}"), ephemeral=True)

        # Permission overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if SUPPORT_ROLE_ID:
            role = guild.get_role(SUPPORT_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        # Use per-category Discord category if set, else fallback to default
        cat_id = TICKET_CATEGORY_MAP.get(key) or TICKET_CATEGORY_ID
        category = guild.get_channel(cat_id) if cat_id else None
        ch = await guild.create_text_channel(
            name=f"ticket-{safe_name}-{key}",
            category=category,
            topic=f"Ticket by {user} ({user.id}) | {label}",
            overwrites=overwrites,
        )

        # Ticket embed — cool style
        colors = [0x5865f2, 0xeb459e, 0x57f287, 0xfee75c, 0x00b0f4]
        import hashlib
        col = colors[int(hashlib.md5(str(user.id).encode()).hexdigest(), 16) % len(colors)]
        e = discord.Embed(
            title=f"{emoji}  {label}",
            description=(
                f"👋 Hey {user.mention}! Welcome to your support ticket.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Please **describe your issue** in detail below.\n"
                f"⏳ A staff member will assist you **shortly**.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**Rules:**\n"
                f"▸ Be patient & respectful\n"
                f"▸ Do not ping staff repeatedly\n"
                f"▸ All conversations are recorded"
            ),
            color=col, timestamp=datetime.now(timezone.utc)
        )
        e.add_field(name="🏷️ Category",  value=f"{emoji} {label}",  inline=True)
        e.add_field(name="👤 Opened by", value=user.mention,          inline=True)
        e.add_field(name="🕐 Time",      value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>", inline=True)
        e.set_footer(text="ZypherNode Support • $ticket close to close • Made by Black Belt")
        e.set_thumbnail(url=user.display_avatar.url)

        ping_content = None
        if TICKET_PING_ROLE_ID:
            ping_content = f"<@&{TICKET_PING_ROLE_ID}>"
        ticket_created_at[ch.id] = datetime.now(timezone.utc)
        await ch.send(
            content=ping_content,
            embed=e,
            view=CloseTicketView()
        )
        await interaction.followup.send(
            embed=ok_embed(f"Your ticket has been created: {ch.mention}"), ephemeral=True)

        # Log
        if TICKET_LOG_ID:
            log_ch = guild.get_channel(TICKET_LOG_ID)
            if log_ch:
                created_ts = datetime.now(timezone.utc).strftime("%A, %d %B, %Y %H:%M")
                le = discord.Embed(title="Ticket Created", color=C_TICKET)
                le.description = f"{user.mention} created a ticket"
                le.add_field(
                    name="Ticket Information",
                    value=(
                        f"\u2502 **Ticket Name:** {label}-{user.name}\n"
                        f"\u2502 **Ticket ID:** {ch.id}\n"
                        f"\u2502 **Created At:** {created_ts}"
                    ),
                    inline=False
                )
                le.add_field(
                    name="Creator Information",
                    value=(
                        f"\u2502 **Creator:** {user.mention}\n"
                        f"\u2502 **Creator Username:** @{user.name}\n"
                        f"\u2502 **Creator ID:** {user.id}"
                    ),
                    inline=False
                )
                le.set_footer(text=f"{BOT_NAME} | Made by Black Belt")
                await log_ch.send(embed=le)


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        view.add_item(TicketCategorySelect())
        await interaction.response.send_message(
            "📋 **Select a topic below to open your ticket:**", view=view, ephemeral=True)


# ticket_claimed: channel_id → claimer_id
ticket_claimed = {}
# ticket_created_at: channel_id → datetime
ticket_created_at = {}

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, emoji="✋", custom_id="ticket_claim_btn", row=0)
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(interaction.user.id)
        is_admin = member.guild_permissions.administrator
        has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in member.roles)
        if not is_admin and not has_support:
            return await interaction.response.send_message(
                embed=err_embed("❌ Only **Admins** or **Staff** can claim tickets."), ephemeral=True)

        ch = interaction.channel
        # Check if already claimed
        if ch.id in ticket_claimed:
            claimer_id = ticket_claimed[ch.id]
            claimer = interaction.guild.get_member(claimer_id)
            claimer_str = claimer.mention if claimer else f"<@{claimer_id}>"
            return await interaction.response.send_message(
                embed=err_embed(f"This ticket is already claimed by {claimer_str}."), ephemeral=True)

        ticket_claimed[ch.id] = member.id

        # Remove all other staff/support access, only claimer + ticket owner + bot + admin
        new_overwrites = {}
        for target, overwrite in ch.overwrites.items():
            # Keep: bot, default_role, admins, ticket owner (has send_messages True explicitly)
            if target == interaction.guild.me:
                new_overwrites[target] = overwrite
            elif target == interaction.guild.default_role:
                new_overwrites[target] = overwrite
            elif isinstance(target, discord.Member) and overwrite.view_channel == True:
                # Keep ticket owner
                new_overwrites[target] = overwrite
            elif isinstance(target, discord.Role) and target.permissions.administrator:
                new_overwrites[target] = overwrite
            # Skip support role - they lose access after claim

        # Add claimer explicitly
        new_overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        cur_topic = ch.topic or ""
        await ch.edit(overwrites=new_overwrites, topic=f"{cur_topic} | Claimed by {member}")

        e = discord.Embed(
            description=f"✋ Ticket claimed by {member.mention}\nOnly they can see this ticket now.",
            color=C_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.send_message(embed=e)

        # Update button to show claimed
        button.label = f"Claimed by {member.display_name}"
        button.disabled = True
        button.style = discord.ButtonStyle.secondary
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn", row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(interaction.user.id)
        is_admin = member.guild_permissions.administrator
        has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in member.roles)
        if not is_admin and not has_support:
            return await interaction.response.send_message(
                embed=err_embed("❌ Only **Admins** or **Staff** can close tickets."), ephemeral=True)
        e = discord.Embed(
            title="🔒 Close Ticket?",
            description="Are you sure you want to close this ticket?",
            color=C_WARN
        )
        await interaction.response.send_message(embed=e, view=ConfirmCloseView(), ephemeral=True)


class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        guild = interaction.guild
        closer = interaction.user

        await interaction.response.send_message(
            embed=discord.Embed(description="🔒 Closing in 5 seconds...", color=C_ERROR))

        # ── Parse ticket info from topic ──────────────────────────────
        topic = ch.topic or ""
        creator = None
        creator_id = None
        import re
        id_match = re.search(r"\((\d+)\)", topic)
        if id_match:
            creator_id = int(id_match.group(1))
            creator = guild.get_member(creator_id)

        # ── Generate transcript ───────────────────────────────────────
        transcript_lines = [f"=== Ticket Transcript: {ch.name} ===\n"]
        async for msg in ch.history(limit=500, oldest_first=True):
            if msg.author.bot and not msg.embeds:
                continue
            ts = msg.created_at.strftime("%d/%m/%Y %H:%M")
            if msg.content:
                transcript_lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {msg.content}")
            for embed in msg.embeds:
                if embed.description:
                    transcript_lines.append(f"[{ts}] {msg.author} [Embed]: {embed.description[:200]}")
            for att in msg.attachments:
                transcript_lines.append(f"[{ts}] {msg.author} [File]: {att.url}")

        transcript_text = "\n".join(transcript_lines)
        transcript_bytes = transcript_text.encode("utf-8")
        transcript_file = discord.File(
            fp=__import__("io").BytesIO(transcript_bytes),
            filename=f"transcript-{ch.name}.txt"
        )

        # ── Send to log channel ───────────────────────────────────────
        if TICKET_LOG_ID:
            log_ch = guild.get_channel(TICKET_LOG_ID)
            if log_ch:
                le = discord.Embed(
                    title="Ticket Closed",
                    color=0x2b2d31,
                    timestamp=datetime.now(timezone.utc)
                )
                le.description = f"{closer.mention} closed a ticket."
                le.add_field(
                    name="Close Information",
                    value=(
                        f"\u2502 **Ticket Name:** {ch.name}\n"
                        f"\u2502 **Ticket ID:** {ch.id}\n"
                        f"\u2502 **Reason:** No further action required."
                    ),
                    inline=False
                )
                if creator:
                    le.add_field(
                        name="Creator Information",
                        value=(
                            f"\u2502 **Creator:** {creator.mention}\n"
                            f"\u2502 **Creator Username:** @{creator.name}\n"
                            f"\u2502 **Creator ID:** {creator.id}"
                        ),
                        inline=False
                    )
                le.add_field(
                    name="Executor Information",
                    value=(
                        f"\u2502 **Executor:** {closer.mention}\n"
                        f"\u2502 **Executor Username:** @{closer.name}\n"
                        f"\u2502 **Executor ID:** {closer.id}"
                    ),
                    inline=False
                )
                le.set_footer(text="Made by Black Belt")

                # Send transcript file separately
                transcript_file2 = discord.File(
                    fp=__import__("io").BytesIO(transcript_bytes),
                    filename=f"transcript-{ch.name}.txt"
                )
                await log_ch.send(embed=le, file=transcript_file2)

        # ── DM ticket creator ─────────────────────────────────────────
        if creator:
            try:
                now = datetime.now(timezone.utc)
                open_time = ch.created_at.strftime("%d %B %Y %H:%M")
                close_time = now.strftime("%d %B %Y %H:%M")
                # Get category/label from topic
                topic = ch.topic or ""
                cat_label = topic.split("|")[1].strip() if "|" in topic else ch.name

                dm_e = discord.Embed(title="Ticket Closed", color=C_ERROR)
                dm_e.description = f"Your ticket has been closed in **{guild.name}**!"
                dm_e.add_field(
                    name="Ticket Information",
                    value=(
                        f"\u2022 **Open Date:** {open_time}\n"
                        f"\u2022 **Panel Name:** {cat_label}\n"
                        f"\u2022 **Ticket Name:** {ch.name}"
                    ),
                    inline=False
                )
                dm_e.add_field(
                    name="Close Information",
                    value=(
                        f"\u2022 **Closed By:** {closer.mention}\n"
                        f"\u2022 **Close Date:** {close_time}\n"
                        f"\u2022 **Close Reason:** Ticket was closed by staff."
                    ),
                    inline=False
                )
                dm_e.set_footer(text=f"If you have any further questions, feel free to open a new ticket. • Made by Black Belt")
                await creator.send(embed=dm_e)
            except:
                pass

        await asyncio.sleep(5)
        await ch.delete(reason=f"Ticket closed by {closer}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=ok_embed("Close cancelled."), view=None)


# ═══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Status rotation ───────────────────────────────────────────────────────────
STATUSES = [
    "streaming:$help for commands",
    "streaming:tickets & invites",
    "streaming:Made by Black Belt",
]

async def auto_close_unclaimed_tickets():
    """Auto-close tickets not claimed within 29 days."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now(timezone.utc)
        to_close = []
        for ch_id, created in list(ticket_created_at.items()):
            if ch_id in ticket_claimed:
                continue  # Already claimed, skip
            age_days = (now - created).days
            if age_days >= 29:
                to_close.append(ch_id)

        for ch_id in to_close:
            for guild in bot.guilds:
                ch = guild.get_channel(ch_id)
                if ch:
                    try:
                        e = discord.Embed(
                            title="⏰ Auto-Closed",
                            description="This ticket was **automatically closed** because no staff claimed it within **29 days**.",
                            color=C_ERROR,
                            timestamp=now
                        )
                        await ch.send(embed=e)
                        await asyncio.sleep(10)
                        await ch.delete(reason="Auto-closed: unclaimed for 29 days")
                        ticket_created_at.pop(ch_id, None)
                        if TICKET_LOG_ID:
                            log_ch = guild.get_channel(TICKET_LOG_ID)
                            if log_ch:
                                le = discord.Embed(title="⏰ Ticket Auto-Closed", color=C_ERROR, timestamp=now)
                                le.add_field(name="Channel", value=ch.name, inline=True)
                                le.add_field(name="Reason",  value="Unclaimed for 29 days", inline=True)
                                await log_ch.send(embed=le)
                    except:
                        pass

        await asyncio.sleep(3600)  # Check every hour


async def rotate_status():
    await bot.wait_until_ready()
    idx = 0
    while not bot.is_closed():
        entry = STATUSES[idx % len(STATUSES)]
        atype, aname = entry.split(":", 1)
        if atype == "streaming":
            activity = discord.Streaming(name=aname, url=STREAM_URL)
            await bot.change_presence(status=discord.Status.online, activity=activity)
        elif atype == "watching":
            await bot.change_presence(status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.watching, name=aname))
        elif atype == "listening":
            await bot.change_presence(status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.listening, name=aname))
        elif atype == "playing":
            await bot.change_presence(status=discord.Status.online,
                activity=discord.Game(name=aname))
        idx += 1
        await asyncio.sleep(30)


@bot.event
async def on_ready():
    print(f"\n╔══════════════════════════════════════╗")
    print(f"║  ✅  {bot.user} is online!")
    print(f"║  📡  Serving {len(bot.guilds)} guild(s)")
    print(f"╚══════════════════════════════════════╝\n")

    # Register persistent views
    bot.add_view(TicketOpenView())
    bot.add_view(CloseTicketView())

    # Cache invites
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except: pass

    await bot.tree.sync()
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} | $help"))
    bot.loop.create_task(rotate_status())
    bot.loop.create_task(auto_close_unclaimed_tickets())
    print("✅  Slash commands synced.")


@bot.event
async def on_invite_create(invite):
    cache = invite_cache.setdefault(invite.guild.id, {})
    cache[invite.code] = invite.uses


@bot.event
async def on_invite_delete(invite):
    cache = invite_cache.get(invite.guild.id, {})
    cache.pop(invite.code, None)


@bot.event
async def on_member_join(member):
    guild = member.guild
    try:
        new_invites = await guild.invites()
        old_cache   = invite_cache.get(guild.id, {})
        used_invite = None

        for inv in new_invites:
            if old_cache.get(inv.code, 0) < inv.uses:
                used_invite = inv
                break

        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            iid      = used_invite.inviter.id
            gkey     = (guild.id, member.id)
            data     = invite_tracker[guild.id][iid]

            # ── Fake: account age check using current FAKE_DAYS ──────────
            account_age_days = (datetime.now(timezone.utc) - member.created_at).days
            is_fake   = (FAKE_DAYS > 0) and (account_age_days < FAKE_DAYS)
            is_rejoin = gkey in member_inviter

            # Undo previous count if rejoin (someone left and rejoined)
            if is_rejoin:
                old_type = member_type.get(gkey, "real")
                if old_type == "real":
                    data["invites"] = max(0, data["invites"] - 1)
                elif old_type == "fake":
                    data["fake"]    = max(0, data["fake"] - 1)
                # left was already incremented on leave, keep it

            # Count new join
            if is_fake:
                data["fake"]    += 1
            elif is_rejoin:
                data["rejoins"] += 1
            else:
                data["invites"] += 1

            member_inviter[gkey] = iid
            member_type[gkey]    = "fake" if is_fake else ("rejoin" if is_rejoin else "real")

            if INVITE_LOG_ID:
                ch = guild.get_channel(INVITE_LOG_ID)
                if ch:
                    total    = data["invites"]
                    joins    = data["invites"] + data["rejoins"] + data["fake"]
                    inv_word = "invites" if total != 1 else "invite"
                    join_type = "🔴 FAKE" if is_fake else ("🔄 REJOIN" if is_rejoin else "✅ NEW")
                    e = discord.Embed(color=0x2b2d31)
                    e.set_author(name="Invite log")
                    e.set_thumbnail(url=used_invite.inviter.display_avatar.url)
                    e.description = (
                        f"**\u00bb\u00bb {used_invite.inviter.display_name} has {total} {inv_word}**\n\n"
                        f"**Joins :** {joins}\n"
                        f"**Left :** {data['left']}\n"
                        f"**Fake :** {data['fake']}\n"
                        f"**Rejoins :** {data['rejoins']}"
                    )
                    e.set_footer(text=f"Joined: {member.display_name} \u2022 Today at {datetime.now().strftime('%H:%M')} • Made by Black Belt")
                    await ch.send(embed=e)
    except: pass





@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    uid = message.author.id

    # ── Remove AFK if user sends a message ──
    if uid in afk_map:
        data = afk_map.pop(uid)
        try:
            member = message.guild.get_member(uid)
            if member and member.nick and member.nick.startswith("[AFK] "):
                await member.edit(nick=member.nick[6:])
        except: pass
        e = discord.Embed(
            description=f"👋 Welcome back, {message.author.mention}! AFK removed.\n"
                        f"🕐 You were AFK for **{time_ago(data['time'])}**",
            color=C_AFK)
        msg = await message.reply(embed=e, mention_author=False)
        await asyncio.sleep(5)
        await msg.delete()

    # ── Notify if a mentioned user is AFK ──
    for user in message.mentions:
        if user.id in afk_map:
            data = afk_map[user.id]
            e = discord.Embed(
                description=f"💤 **{user.display_name}** is AFK: {data['reason']}\n"
                            f"🕐 Since {time_ago(data['time'])}",
                color=C_AFK)
            await message.reply(embed=e, mention_author=False)

    await bot.process_commands(message)


# ═══════════════════════════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

tree = bot.tree

# ════════════════════ TICKET GROUP ════════════════════

ticket_group = app_commands.Group(name="ticket", description="Ticket system")

def build_panel_embed(guild) -> discord.Embed:
    """Build the ticket panel embed from PANEL_CONFIG"""
    cfg   = PANEL_CONFIG
    rules = "\n".join(f"• {r}" for r in cfg["rules"])
    e = discord.Embed(
        title=cfg["title"],
        description=(
            f"{cfg['description']}\n\n"
            f"🔷 **RULES TO FOLLOW:**\n{rules}\n\n"
            f"Must read 📋 all guidelines before any purchase\n\n"
            f"📅 **Support Timings:**\n"
            f"• {cfg['support_hours']}\n"
            f"• Early Morning : No Support"
        ),
        color=cfg["color"]
    )
    e.set_footer(text=cfg["footer"],
                 icon_url=guild.icon.url if guild.icon else None)
    return e


@ticket_group.command(name="panel", description="Send the ticket panel (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    await interaction.channel.send(embed=build_panel_embed(interaction.guild), view=TicketOpenView())
    await interaction.response.send_message(embed=ok_embed("Ticket panel sent!"), ephemeral=True)


@ticket_group.command(name="setup", description="Customize the ticket panel (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_setup(interaction: discord.Interaction):
    cfg = PANEL_CONFIG
    rules_preview = "\n".join(f"• {r}" for r in cfg["rules"]) or "None set"
    e = discord.Embed(
        title="⚙️ Ticket Panel Setup",
        color=C_INFO,
        description="Click the buttons below to customize your ticket panel."
    )
    e.add_field(name="📌 Current Title",  value=cfg["title"],         inline=False)
    e.add_field(name="🕐 Support Hours",  value=cfg["support_hours"], inline=True)
    e.add_field(name="📝 Footer",         value=cfg["footer"],        inline=True)
    e.add_field(name="📋 Rules",          value=rules_preview,        inline=False)
    e.set_footer(text="Made by Black Belt")
    await interaction.response.send_message(embed=e, view=TicketSetupView(interaction.user.id), ephemeral=True)


@ticket_group.command(name="setrules", description="Set ticket panel rules (Admin) — separate with |")
@app_commands.describe(rules="Rules separated by | e.g. Be patient | No spam | Respect staff")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_setrules(interaction: discord.Interaction, rules: str):
    PANEL_CONFIG["rules"] = [r.strip() for r in rules.split("|") if r.strip()]
    await interaction.response.send_message(
        embed=ok_embed(f"Rules updated! {len(PANEL_CONFIG['rules'])} rules set."), ephemeral=True)


@ticket_group.command(name="sethours", description="Set support hours shown on panel (Admin)")
@app_commands.describe(hours="e.g. 10:00 AM to 10:00 PM")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_sethours(interaction: discord.Interaction, hours: str):
    PANEL_CONFIG["support_hours"] = hours
    await interaction.response.send_message(
        embed=ok_embed(f"Support hours updated to: **{hours}**"), ephemeral=True)

@ticket_group.command(name="close", description="Close this ticket")
async def ticket_close(interaction: discord.Interaction):
    if not interaction.channel.name.startswith("ticket-"):
        return await interaction.response.send_message(
            embed=err_embed("This is not a ticket channel."), ephemeral=True)
    member = interaction.guild.get_member(interaction.user.id)
    is_admin = member.guild_permissions.administrator
    has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in member.roles)
    if not is_admin and not has_support:
        return await interaction.response.send_message(
            embed=err_embed("❌ Only **Admins** or **Staff** can close tickets."), ephemeral=True)
    e = discord.Embed(title="🔒 Close Ticket?",
                      description="Are you sure you want to close this ticket?", color=C_WARN)
    await interaction.response.send_message(embed=e, view=ConfirmCloseView())

@ticket_group.command(name="add", description="Add a user to the ticket")
@app_commands.describe(user="User to add")
async def ticket_add(interaction: discord.Interaction, user: discord.Member):
    # Allow if admin, support role, or ticket owner (their ID in topic)
    member = interaction.guild.get_member(interaction.user.id)
    is_admin = member.guild_permissions.administrator
    has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in member.roles)
    is_owner = interaction.channel.topic and str(interaction.user.id) in interaction.channel.topic
    if not is_admin and not has_support and not is_owner:
        return await interaction.response.send_message(
            embed=err_embed("Only the ticket owner or staff can add users."), ephemeral=True)
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(embed=ok_embed(f"Added {user.mention} to the ticket."))

@ticket_group.command(name="remove", description="Remove a user from the ticket")
@app_commands.describe(user="User to remove")
async def ticket_remove(interaction: discord.Interaction, user: discord.Member):
    await interaction.channel.set_permissions(user, view_channel=False)
    await interaction.response.send_message(embed=ok_embed(f"Removed {user.mention} from the ticket."))

@ticket_group.command(name="rename", description="Rename the ticket channel")
@app_commands.describe(name="New channel name")
async def ticket_rename(interaction: discord.Interaction, name: str):
    clean = re.sub(r"\s+", "-", name.lower())
    await interaction.channel.edit(name=clean)
    await interaction.response.send_message(embed=ok_embed(f"Renamed to `{clean}`."))

@ticket_group.command(name="claim", description="Claim this ticket (staff)")
async def ticket_claim(interaction: discord.Interaction):
    await interaction.channel.edit(topic=f"Claimed by {interaction.user}")
    e = discord.Embed(description=f"✅ Ticket claimed by {interaction.user.mention}.", color=C_SUCCESS)
    await interaction.response.send_message(embed=e)

tree.add_command(ticket_group)

# ════════════════════ AFK ════════════════════

@tree.command(name="afk", description="Set your AFK status")
@app_commands.describe(reason="AFK reason")
async def afk_cmd(interaction: discord.Interaction, reason: str = "AFK"):
    afk_map[interaction.user.id] = {"reason": reason, "time": datetime.now(timezone.utc)}
    try:
        member = interaction.guild.get_member(interaction.user.id)
        nick = member.nick or member.name
        if not nick.startswith("[AFK] "):
            await member.edit(nick=f"[AFK] {nick[:24]}")
    except: pass
    e = discord.Embed(title="💤 AFK Set",
                      description=f"You are now AFK.\n**Reason:** {reason}",
                      color=C_AFK, timestamp=datetime.now(timezone.utc))
    e.set_footer(text="You'll be unset when you send a message. • Made by Black Belt")
    await interaction.response.send_message(embed=e)

# ════════════════════ MODERATION ════════════════════

@tree.command(name="timeout", description="Timeout a member")
@app_commands.describe(user="Member", duration="Duration e.g. 10m 1h 2d", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout_cmd(interaction: discord.Interaction, user: discord.Member,
                      duration: str, reason: str = "No reason provided"):
    td = parse_duration(duration)
    if not td:
        return await interaction.response.send_message(
            embed=err_embed("Invalid duration. Use e.g. `10m`, `1h`, `2d`."), ephemeral=True)
    if td > timedelta(days=28):
        return await interaction.response.send_message(
            embed=err_embed("Max timeout is 28 days."), ephemeral=True)
    try:
        until = datetime.now(timezone.utc) + td
        await user.timeout(until, reason=reason)
        e = discord.Embed(title="⏱️ Member Timed Out", color=C_WARN, timestamp=datetime.now(timezone.utc))
        e.add_field(name="Member",    value=f"{user.mention} ({user.id})", inline=True)
        e.add_field(name="Duration",  value=fmt_delta(td),                inline=True)
        e.add_field(name="Reason",    value=reason,                       inline=False)
        e.add_field(name="Moderator", value=interaction.user.mention,     inline=True)
        await interaction.response.send_message(embed=e)
        await send_mod_log(interaction.guild, "Timeout", user, user.id,
                           interaction.user, reason, C_WARN)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)), ephemeral=True)

@tree.command(name="untimeout", description="Remove timeout from a member")
@app_commands.describe(user="Member")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout_cmd(interaction: discord.Interaction, user: discord.Member):
    try:
        await user.timeout(None)
        await interaction.response.send_message(embed=ok_embed(f"Removed timeout from {user.mention}."))
        await send_mod_log(interaction.guild, "Un-Timeout", user, user.id,
                           interaction.user, "Manual remove", C_SUCCESS)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)), ephemeral=True)

@tree.command(name="kick", description="Kick a member")
@app_commands.describe(user="Member", reason="Reason")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, user: discord.Member,
                   reason: str = "No reason provided"):
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(
            embed=ok_embed(f"👢 Kicked **{user}** | Reason: {reason}"))
        await send_mod_log(interaction.guild, "Kick", user, user.id,
                           interaction.user, reason, C_ERROR)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)), ephemeral=True)

@tree.command(name="ban", description="Ban a member")
@app_commands.describe(user="Member", reason="Reason", delete_days="Delete messages (0-7 days)")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, user: discord.Member,
                  reason: str = "No reason provided", delete_days: int = 0):
    try:
        await user.ban(reason=reason, delete_message_days=min(delete_days, 7))
        await interaction.response.send_message(
            embed=ok_embed(f"🔨 Banned **{user}** | Reason: {reason}"))
        await send_mod_log(interaction.guild, "Ban", user, user.id,
                           interaction.user, reason, C_ERROR)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)), ephemeral=True)

@tree.command(name="unban", description="Unban a user by ID")
@app_commands.describe(user_id="User ID to unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(int(user_id)))
        await interaction.response.send_message(embed=ok_embed(f"Unbanned user `{user_id}`."))
        await send_mod_log(interaction.guild, "Unban", user_id, user_id,
                           interaction.user, "Manual unban", C_SUCCESS)
    except Exception as ex:
        await interaction.response.send_message(embed=err_embed(str(ex)), ephemeral=True)

@tree.command(name="warn", description="Warn a member")
@app_commands.describe(user="Member", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_cmd(interaction: discord.Interaction, user: discord.Member, reason: str):
    key = (interaction.guild.id, user.id)
    warn_map[key].append({"reason": reason, "mod": str(interaction.user), "time": datetime.now(timezone.utc)})
    count = len(warn_map[key])
    e = discord.Embed(title="⚠️ Warning Issued", color=C_WARN, timestamp=datetime.now(timezone.utc))
    e.add_field(name="User",   value=f"{user.mention} ({user.id})", inline=True)
    e.add_field(name="Warn #", value=str(count),                   inline=True)
    e.add_field(name="Reason", value=reason,                       inline=False)
    try: await user.send(embed=e)
    except: pass
    await interaction.response.send_message(embed=e)
    await send_mod_log(interaction.guild, "Warn", user, user.id,
                       interaction.user, reason, C_WARN)

@tree.command(name="warnings", description="View warnings of a member")
@app_commands.describe(user="Member")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member):
    key  = (interaction.guild.id, user.id)
    warns = warn_map.get(key, [])
    if not warns:
        return await interaction.response.send_message(
            embed=ok_embed(f"{user} has no warnings."))
    lines = "\n\n".join(
        f"**#{i+1}** — {w['reason']}\n> by {w['mod']} • <t:{int(w['time'].timestamp())}:R>"
        for i, w in enumerate(warns))
    e = discord.Embed(title=f"⚠️ Warnings for {user}", description=lines,
                      color=C_WARN)
    e.set_footer(text=f"Total: {len(warns)} • Made by Black Belt")
    await interaction.response.send_message(embed=e)

@tree.command(name="clearwarns", description="Clear all warnings for a member")
@app_commands.describe(user="Member")
@app_commands.checks.has_permissions(administrator=True)
async def clearwarns_cmd(interaction: discord.Interaction, user: discord.Member):
    warn_map.pop((interaction.guild.id, user.id), None)
    await interaction.response.send_message(embed=ok_embed(f"Cleared all warnings for {user.mention}."))

@tree.command(name="purge", description="Delete multiple messages")
@app_commands.describe(amount="Messages to delete (1-100)", user="Only from this user")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge_cmd(interaction: discord.Interaction, amount: int,
                    user: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    amount = max(1, min(amount, 100))
    check  = (lambda m: m.author == user) if user else None
    deleted = await interaction.channel.purge(limit=amount, check=check,
                                               before=interaction.created_at)
    await interaction.followup.send(embed=ok_embed(f"Deleted **{len(deleted)}** message(s)."))

@tree.command(name="lock", description="Lock a channel")
@app_commands.describe(channel="Channel to lock (default: current)")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    ch = channel or interaction.channel
    await ch.set_permissions(interaction.guild.default_role, send_messages=False)
    e = discord.Embed(description=f"🔒 {ch.mention} has been **locked**.", color=C_ERROR)
    await interaction.response.send_message(embed=e)
    if ch != interaction.channel:
        await ch.send(embed=e)

@tree.command(name="unlock", description="Unlock a channel")
@app_commands.describe(channel="Channel to unlock (default: current)")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    ch = channel or interaction.channel
    await ch.set_permissions(interaction.guild.default_role, send_messages=None)
    e = discord.Embed(description=f"🔓 {ch.mention} has been **unlocked**.", color=C_SUCCESS)
    await interaction.response.send_message(embed=e)
    if ch != interaction.channel:
        await ch.send(embed=e)

@tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.describe(seconds="Seconds (0 to disable)", channel="Channel (default: current)")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode_cmd(interaction: discord.Interaction, seconds: int,
                       channel: discord.TextChannel = None):
    ch = channel or interaction.channel
    await ch.edit(slowmode_delay=max(0, min(seconds, 21600)))
    msg = f"Slowmode disabled in {ch.mention}." if seconds == 0 \
        else f"Slowmode set to **{seconds}s** in {ch.mention}."
    await interaction.response.send_message(embed=ok_embed(msg))

@tree.command(name="note", description="Add or view staff notes on a user")
@app_commands.describe(user="Member", text="Note text (leave blank to view notes)")
@app_commands.checks.has_permissions(moderate_members=True)
async def note_cmd(interaction: discord.Interaction, user: discord.Member,
                   text: str = None):
    key = (interaction.guild.id, user.id)
    if not text:
        notes = note_map.get(key, [])
        if not notes:
            return await interaction.response.send_message(
                embed=ok_embed(f"No notes for {user}."), ephemeral=True)
        lines = "\n\n".join(
            f"**#{i+1}** — {n['text']}\n> by {n['mod']} • <t:{int(n['time'].timestamp())}:R>"
            for i, n in enumerate(notes))
        e = discord.Embed(title=f"📝 Notes for {user}", description=lines, color=C_INFO)
        return await interaction.response.send_message(embed=e, ephemeral=True)
    note_map[key].append({"text": text, "mod": str(interaction.user), "time": datetime.now(timezone.utc)})
    await interaction.response.send_message(
        embed=ok_embed(f"Note added for {user.mention}."), ephemeral=True)

# ════════════════════ INVITE TRACKING ════════════════════

@tree.command(name="invites", description="Check invite stats for a user")
@app_commands.describe(user="User (default: yourself)")
async def invites_cmd(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    target   = user or interaction.guild.get_member(interaction.user.id)
    data     = invite_tracker[interaction.guild.id][target.id]
    total    = data["invites"]
    joins    = data["invites"] + data["rejoins"]
    left     = data["left"]
    fake     = data["fake"]
    rejoins  = data["rejoins"]
    time_str = datetime.now().strftime("%H:%M")

    e = discord.Embed(color=0x2b2d31)
    e.set_author(name="Invite log")
    e.set_thumbnail(url=target.display_avatar.url)
    inv_word = "invites" if total != 1 else "invite"
    e.description = (
        f"**\u00bb\u00bb {target.display_name} has {total} {inv_word}**\n\n"
        f"**Joins :** {joins}\n"
        f"**Left :** {left}\n"
        f"**Fake :** {fake}\n"
        f"**Rejoins :** {rejoins}"
    )
    e.set_footer(text=f"Requested by {interaction.user.display_name} \u2022 Today at {time_str} • Made by Black Belt")
    await interaction.followup.send(embed=e)

@tree.command(name="inviteboard", description="Top invite leaderboard")
async def inviteboard_cmd(interaction: discord.Interaction):
    gdata  = invite_tracker.get(interaction.guild.id, {})
    sorted_data = sorted(gdata.items(), key=lambda x: x[1]["invites"], reverse=True)[:10]
    if not sorted_data:
        return await interaction.response.send_message(
            embed=err_embed("No invite data yet."), ephemeral=True)
    medals = ["🥇", "🥈", "🥉"]
    lines  = [f"{medals[i] if i < 3 else f'**{i+1}.**'} <@{uid}> — **{d['invites']}** invites"
              for i, (uid, d) in enumerate(sorted_data)]
    e = discord.Embed(title="📨 Invite Leaderboard", description="\n".join(lines),
                      color=C_INVITE, timestamp=datetime.now(timezone.utc))
    await interaction.response.send_message(embed=e)

@tree.command(name="resetinvites", description="Reset invite count for a user (Admin)")
@app_commands.describe(user="User to reset")
@app_commands.checks.has_permissions(administrator=True)
async def resetinvites_cmd(interaction: discord.Interaction, user: discord.Member):
    invite_tracker[interaction.guild.id].pop(user.id, None)
    await interaction.response.send_message(
        embed=ok_embed(f"Reset invite count for {user.mention}."))

# ════════════════════ UTILITY ════════════════════

@tree.command(name="userinfo", description="View info about a user")
@app_commands.describe(user="User (default: yourself)")
async def userinfo_cmd(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.guild.get_member(interaction.user.id)
    roles  = [r.mention for r in target.roles if r != interaction.guild.default_role]
    e = discord.Embed(title=f"👤 {target}", color=C_PRIMARY, timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="ID",             value=str(target.id), inline=True)
    e.add_field(name="Bot",            value="Yes" if target.bot else "No", inline=True)
    e.add_field(name="Account Created",
                value=f"<t:{int(target.created_at.timestamp())}:R>", inline=True)
    e.add_field(name="Joined Server",
                value=f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "N/A", inline=True)
    e.add_field(name="Roles",
                value=" ".join(roles) if roles else "None", inline=False)
    await interaction.response.send_message(embed=e)

@tree.command(name="serverinfo", description="View info about the server")
async def serverinfo_cmd(interaction: discord.Interaction):
    g = interaction.guild
    e = discord.Embed(title=f"🏠 {g.name}", color=C_PRIMARY, timestamp=datetime.now(timezone.utc))
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Owner",        value=f"<@{g.owner_id}>",                    inline=True)
    e.add_field(name="Members",      value=str(g.member_count),                   inline=True)
    e.add_field(name="Channels",     value=str(len(g.channels)),                  inline=True)
    e.add_field(name="Roles",        value=str(len(g.roles)),                     inline=True)
    e.add_field(name="Boosts",       value=str(g.premium_subscription_count),     inline=True)
    e.add_field(name="Verification", value=str(g.verification_level).title(),     inline=True)
    e.add_field(name="Created",
                value=f"<t:{int(g.created_at.timestamp())}:R>",                   inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="avatar", description="Get avatar of a user")
@app_commands.describe(user="User (default: yourself)")
async def avatar_cmd(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    e = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=C_PRIMARY)
    e.set_image(url=target.display_avatar.replace(size=1024).url)
    e.url = target.display_avatar.replace(size=4096).url
    await interaction.response.send_message(embed=e)

@tree.command(name="ping", description="Check bot latency")
async def ping_cmd(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    e = discord.Embed(title="🏓 Pong!", color=C_INFO)
    e.add_field(name="Bot Latency", value=f"{latency}ms",  inline=True)
    e.add_field(name="API Latency", value=f"{latency}ms",  inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="botinfo", description="View bot info and feature list")
async def botinfo_cmd(interaction: discord.Interaction):
    e = discord.Embed(
        title=f"🤖 {BOT_NAME} Bot",
        description=f"A full-featured Discord bot for {BOT_NAME} community management.",
        color=C_PRIMARY, timestamp=datetime.now(timezone.utc)
    )
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(
        name="📋 Features",
        value=(
            "🎫 **Ticket System** — Multi-category support tickets\n"
            "⏱️ **Timeout System** — Flexible duration moderation\n"
            "💤 **AFK System** — Auto nick update + ping reply\n"
            "📨 **Invite Tracking** — Leaderboard & per-invite stats\n"
            "⚠️ **Warn System** — DM warnings with history\n"
            "🔒 **Lock / Unlock** — Channel management\n"
            "🗑️ **Purge** — Bulk message deletion\n"
            "🔇 **Slowmode** — Rate limit control\n"
            "📝 **Staff Notes** — Private notes on members\n"
            "📊 **Userinfo / Serverinfo** — Quick lookups"
        ), inline=False
    )
    e.add_field(name="Servers", value=str(len(bot.guilds)),    inline=True)
    e.add_field(name="Users",   value=str(len(bot.users)),     inline=True)
    await interaction.response.send_message(embed=e)

# ─── Global error handler ───────────────────────────────────────────────────
@tree.error
async def on_app_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=err_embed("You don't have permission to use this command."), ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message(
            embed=err_embed(f"I'm missing permissions: {error.missing_permissions}"), ephemeral=True)
    else:
        print(f"[ERROR] {error}")
        try:
            await interaction.response.send_message(
                embed=err_embed(f"An error occurred: {error}"), ephemeral=True)
        except: pass


# ═══════════════════════════════════════════════════════════════════════════════
#  PREFIX COMMANDS  (! wala)
# ═══════════════════════════════════════════════════════════════════════════════

# ── !help ──────────────────────────────────────────────────────────────────────

# ── Help Category Select ──────────────────────────────────────────────────────
HELP_CATEGORIES = [
    discord.SelectOption(label="Index",          value="index",   emoji="🏠", description="How to use the bot"),
    discord.SelectOption(label="Ticket System",  value="ticket",  emoji="🎫", description="Ticket commands & setup"),
    discord.SelectOption(label="Moderation",     value="mod",     emoji="🛡️", description="Ban, kick, warn, timeout"),
    discord.SelectOption(label="Invite Logging", value="invite",  emoji="📨", description="Invite tracking feature"),
    discord.SelectOption(label="Giveaways",      value="giveaway",emoji="🎁", description="Giveaway system"),
    discord.SelectOption(label="Timer",          value="timer",   emoji="⏱️", description="Timer feature"),
    discord.SelectOption(label="AFK",            value="afk",     emoji="💤", description="AFK system"),
    discord.SelectOption(label="Utility",        value="util",    emoji="🔧", description="Useful commands"),
    discord.SelectOption(label="Logs",           value="logs",    emoji="📋", description="Ticket & bot log setup"),
]

def get_help_embed(value: str, guild) -> discord.Embed:
    P = "$"
    if value == "index":
        e = discord.Embed(title=f"🏠 {BOT_NAME} Bot — Index", color=C_PRIMARY)
        e.description = (
            f"**Hey there! My prefix in this server is `$`**\n\n"
            f"Use the dropdown below to browse commands.\n\n"
            f"🎫 **Ticket System** — Support ticket management\n"
            f"🛡️ **Moderation** — Ban, kick, warn, timeout\n"
            f"📨 **Invite Logging** — Track who invited who\n"
            f"🎁 **Giveaways** — Run giveaways easily\n"
            f"⏱️ **Timer** — Set timers\n"
            f"💤 **AFK** — AFK status system\n"
            f"🔧 **Utility** — Userinfo, avatar, ping\n"
            f"📋 **Logs** — Set ticket & bot log channels"
        )
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.set_footer(text=f"{BOT_NAME} Bot • Prefix: $ • Made by Black Belt")


    elif value == "ticket":
        cats = " · ".join(f"{em} {lbl}" for _, (em, lbl, _) in list(TICKET_CATEGORIES.items())[:6])
        e = discord.Embed(title="🎫 Ticket System", color=C_TICKET)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Manage support tickets with categories & logging.**"
        e.add_field(name="Panel Commands:", inline=False, value=(
            f"`{P}ticket panel` — Send ticket panel *(Admin)*\n"
            f"`{P}ticket setup` — Customize panel interactively *(Admin)*"
        ))
        e.add_field(name="Ticket Commands:", inline=False, value=(
            f"`{P}ticket close` — Close & delete the ticket *(Staff)*\n"
            f"`{P}ticket claim` — Claim ticket *(Staff)*\n"
            f"`{P}ticket add @user` — Add user to ticket\n"
            f"`{P}ticket remove @user` — Remove user from ticket\n"
            f"`{P}ticket rename <n>` — Rename the ticket channel"
        ))
        e.add_field(name="Setup Commands:", inline=False, value=(
            f"`{P}ticket setclosedm <msg>` — Set DM on close *(Admin)*\n"
            f"Placeholders: `{{ticket_name}}` `{{closer}}`\n"
            f"`{P}ticket setping @role` — Set ping role *(Admin)*\n"
            f"`{P}ticket setcategory <type> #cat` — Set Discord category *(Admin)*\n"
            f"`{P}ticket addcat <emoji> <n>` — Add ticket type *(Admin)*\n"
            f"`{P}ticket removecat <n>` — Remove ticket type *(Admin)*\n"
            f"`{P}ticket listcats` — List all ticket types"
        ))
        e.add_field(name="Categories:", inline=False, value=cats or "No categories set")
        e.set_footer(text=f"{BOT_NAME} Bot • Prefix: $ • {len(TICKET_CATEGORIES)} categories • Made by Black Belt")

    elif value == "mod":
        e = discord.Embed(title="🛡️ Moderation", color=C_ERROR)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Moderation commands. Requires appropriate permissions.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}ban @user [reason]` — Ban a member\n"
            f"`{P}unban <id>` — Unban by ID\n"
            f"`{P}kick @user [reason]` — Kick a member\n"
            f"`{P}timeout @u 10m [reason]` — Timeout\n"
            f"`{P}untimeout @user` — Remove timeout\n"
            f"`{P}warn @user <reason>` — Warn (DMs user)\n"
            f"`{P}warnings @user` — View warnings\n"
            f"`{P}clearwarns @user` — Clear all warnings\n"
            f"`{P}purge <1-100>` — Bulk delete messages\n"
            f"`{P}lock / {P}unlock` — Lock/unlock channel\n"
            f"`{P}slowmode <sec>` — Set slowmode\n"
            f"`{P}note @user [text]` — Staff notes"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "invite":
        e = discord.Embed(title="📨 Invite Logging", color=C_INVITE)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Track who invited who to the server.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}i [@user]` — Invite stats (joins/left/fake/rejoins)\n"
            f"`{P}invited [@user]` — List of who they invited\n"
            f"`{P}lb` — Invite leaderboard\n"
            f"`{P}resetinvites @user` — Reset invite count *(Admin)*"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "giveaway":
        e = discord.Embed(title="🎁 Giveaways", color=discord.Color.gold())
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Run and manage giveaways easily.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}gstart <time> <winners> <prize>` — Start a giveaway\n"
            f"Example: `{P}gstart 1h 2 Nitro`\n"
            f"`{P}gend <msg_id>` — End giveaway early\n"
            f"`{P}greroll <msg_id>` — Reroll new winner"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "timer":
        e = discord.Embed(title="⏱️ Timer", color=discord.Color.orange())
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Set timers — bot will ping you when done.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}tstart <duration> <label>` — Set a timer\n"
            f"Example: `{P}tstart 30m Study Break`\n"
            f"Durations: `10s` `5m` `2h` `1d`"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "afk":
        e = discord.Embed(title="💤 AFK System", color=C_AFK)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Set yourself as AFK.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}afk [reason]` — Set AFK status\n"
            f"• Adds `[AFK]` prefix to nickname\n"
            f"• Auto-replies when someone pings you\n"
            f"• Auto-removes when you send a message"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "util":
        e = discord.Embed(title="🔧 Utility", color=C_INFO)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Useful commands for everyone.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}userinfo [@user]` — Detailed user info\n"
            f"`{P}serverinfo` — Server info\n"
            f"`{P}mc` — Member count\n"
            f"`{P}accage <id/@u>` — Account age\n"
            f"`{P}avatar [@user]` — Get user avatar\n"
            f"`{P}ping` — Bot latency\n"
            f"`{P}botinfo` — Bot features"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")

    elif value == "logs":
        e = discord.Embed(title="📋 Log Setup", color=C_INFO)
        e.set_thumbnail(url=guild.me.display_avatar.url)
        e.description = "**Set channels for ticket and bot logs.**"
        e.add_field(name="Commands:", inline=False, value=(
            f"`{P}setticketlog #channel` — Set ticket log channel *(Admin)*\n"
            f"`{P}setbotlog #channel` — Set bot log channel *(Admin)*\n"
            f"`{P}setmodlog #channel` — Set mod log channel *(Admin)*"
        ))
        e.set_footer(text="ZypherNode Bot • Prefix: $ • Made by Black Belt")
    else:
        e = discord.Embed(title="❓ Unknown", color=C_ERROR, description="Select a category from the dropdown.")

    e.set_footer(text="Made by Black Belt")
    return e


class HelpSelect(discord.ui.Select):
    def __init__(self, guild):
        self.guild = guild
        super().__init__(placeholder="Select a category...", min_values=1, max_values=1, options=HELP_CATEGORIES)

    async def callback(self, interaction: discord.Interaction):
        e = get_help_embed(self.values[0], self.view.guild)
        await interaction.response.edit_message(embed=e, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=120)
        self.guild = guild
        self.add_item(HelpSelect(guild))


@bot.command(name="help", aliases=["h", "commands", "cmds"])
async def help_cmd(ctx, category: str = None):
    val = category.lower() if category else "index"
    e = get_help_embed(val, ctx.guild)
    view = HelpView(ctx.guild)
    await ctx.send(embed=e, view=view)


# ── !ticket ────────────────────────────────────────────────────────────────────
@bot.group(name="ticket", invoke_without_command=True)
async def ticket_prefix(ctx):
    await ctx.send(embed=err_embed("Usage: `$ticket panel / close / add / remove / rename / claim`"))

@ticket_prefix.command(name="panel")
@commands.has_permissions(administrator=True)
async def tp_panel(ctx):
    await ctx.channel.send(embed=build_panel_embed(ctx.guild), view=TicketOpenView())
    await ctx.send(embed=ok_embed("Ticket panel sent!"), delete_after=5)


@ticket_prefix.command(name="setup")
@commands.has_permissions(administrator=True)
async def tp_setup(ctx):
    cfg = PANEL_CONFIG
    rules_preview = "\n".join(f"• {r}" for r in cfg["rules"]) or "None set"
    e = discord.Embed(
        title="⚙️ Ticket Panel Setup",
        color=C_INFO,
        description="Click the buttons below to customize your ticket panel."
    )
    e.add_field(name="📌 Current Title",    value=cfg["title"],           inline=False)
    e.add_field(name="🕐 Support Hours",    value=cfg["support_hours"],   inline=True)
    e.add_field(name="📝 Footer",           value=cfg["footer"],          inline=True)
    e.add_field(name="📋 Rules",            value=rules_preview,          inline=False)
    e.set_footer(text="Made by Black Belt")
    await ctx.send(embed=e, view=TicketSetupView(ctx.author.id))

@ticket_prefix.command(name="close")
async def tp_close(ctx):
    if not ctx.channel.name.startswith("ticket-"):
        return await ctx.send(embed=err_embed("This is not a ticket channel."))
    is_admin = ctx.author.guild_permissions.administrator
    has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in ctx.author.roles)
    if not is_admin and not has_support:
        return await ctx.send(embed=err_embed("❌ Only **Admins** or **Staff** can close tickets."), delete_after=5)
    await ctx.send(embed=discord.Embed(description="🔒 Closing in 5 seconds...", color=C_ERROR))
    ch = ctx.channel
    closer = ctx.author
    guild = ctx.guild
    topic = ch.topic or ""
    creator = None
    import re, io
    id_match = re.search(r"\((\d+)\)", topic)
    if id_match:
        creator = guild.get_member(int(id_match.group(1)))

    transcript_lines = [f"=== Ticket Transcript: {ch.name} ===\n"]
    async for msg in ch.history(limit=500, oldest_first=True):
        if msg.author.bot and not msg.embeds: continue
        ts = msg.created_at.strftime("%d/%m/%Y %H:%M")
        if msg.content:
            transcript_lines.append(f"[{ts}] {msg.author}: {msg.content}")
    transcript_bytes = "\n".join(transcript_lines).encode("utf-8")

    if TICKET_LOG_ID:
        lch = guild.get_channel(TICKET_LOG_ID)
        if lch:
            le = discord.Embed(title="Ticket Closed", color=0x2b2d31, timestamp=datetime.now(timezone.utc))
            le.description = f"{closer.mention} closed a ticket."
            le.add_field(name="Close Information",
                value=f"\u2502 **Ticket Name:** {ch.name}\n\u2502 **Ticket ID:** {ch.id}\n\u2502 **Reason:** No further action required.",
                inline=False)
            if creator:
                le.add_field(name="Creator Information",
                    value=f"\u2502 **Creator:** {creator.mention}\n\u2502 **Username:** @{creator.name}\n\u2502 **ID:** {creator.id}",
                    inline=False)
            le.add_field(name="Executor Information",
                value=f"\u2502 **Executor:** {closer.mention}\n\u2502 **Username:** @{closer.name}\n\u2502 **ID:** {closer.id}",
                inline=False)
            le.set_footer(text="Made by Black Belt")
            await lch.send(embed=le, file=discord.File(fp=io.BytesIO(transcript_bytes), filename=f"transcript-{ch.name}.txt"))

    await asyncio.sleep(5)
    await ctx.channel.delete()

@ticket_prefix.command(name="add")
async def tp_add(ctx, member: discord.Member):
    is_admin = ctx.author.guild_permissions.administrator
    has_support = SUPPORT_ROLE_ID and any(r.id == SUPPORT_ROLE_ID for r in ctx.author.roles)
    is_owner = ctx.channel.topic and str(ctx.author.id) in ctx.channel.topic
    if not is_admin and not has_support and not is_owner:
        return await ctx.send(embed=err_embed("Only the ticket owner or staff can add users."), delete_after=5)
    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await ctx.send(embed=ok_embed(f"Added {member.mention} to the ticket."))

@ticket_prefix.command(name="remove")
async def tp_remove(ctx, member: discord.Member):
    await ctx.channel.set_permissions(member, view_channel=False)
    await ctx.send(embed=ok_embed(f"Removed {member.mention} from the ticket."))

@ticket_prefix.command(name="rename")
async def tp_rename(ctx, *, name: str):
    clean = re.sub(r"\s+", "-", name.lower())
    await ctx.channel.edit(name=clean)
    await ctx.send(embed=ok_embed(f"Renamed to `{clean}`."))

@ticket_prefix.command(name="claim")
async def tp_claim(ctx):
    await ctx.channel.edit(topic=f"Claimed by {ctx.author}")
    await ctx.send(embed=discord.Embed(description=f"✅ Claimed by {ctx.author.mention}.", color=C_SUCCESS))



# ═══════════════════════════════════════════════════════════════════════════════
#  TICKET CATEGORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@ticket_prefix.command(name="setclosedm", aliases=["closedm", "dmclose"])
@commands.has_permissions(administrator=True)
async def tp_setclosedm(ctx, *, message: str = None):
    """Set DM message sent when ticket closes.
    Use {ticket_name} and {closer} as placeholders.
    Leave empty to disable DM."""
    global TICKET_CLOSE_DM
    if not message:
        TICKET_CLOSE_DM = ""
        return await ctx.send(embed=ok_embed("Close DM disabled. No DM will be sent on ticket close."))
    TICKET_CLOSE_DM = message
    preview = message.replace("{ticket_name}", "ticket-example").replace("{closer}", ctx.author.display_name)
    e = discord.Embed(color=C_SUCCESS)
    e.description = f"✅ Close DM message set!\n\n**Preview:**\n{preview}"
    e.set_footer(text="Use {ticket_name} and {closer} as placeholders • Made by Black Belt")
    await ctx.send(embed=e)


@ticket_prefix.command(name="setping")
@commands.has_permissions(administrator=True)
async def tp_setping(ctx, *, role_input: str = None):
    global TICKET_PING_ROLE_ID
    if not role_input:
        TICKET_PING_ROLE_ID = 0
        return await ctx.send(embed=ok_embed("Ping role removed."))
    # Find by mention, ID or name
    import re
    role = None
    mention_match = re.match(r"<@&(\d+)>", role_input.strip())
    if mention_match:
        role = ctx.guild.get_role(int(mention_match.group(1)))
    if not role and role_input.strip().isdigit():
        role = ctx.guild.get_role(int(role_input.strip()))
    if not role:
        role = discord.utils.find(lambda r: r.name.lower() == role_input.strip().lstrip("@").lower(), ctx.guild.roles)
    if not role:
        return await ctx.send(embed=err_embed(f"Role `{role_input}` not found."))
    TICKET_PING_ROLE_ID = role.id
    await ctx.send(embed=ok_embed(f"Ping role set to {role.mention}"))


@ticket_prefix.command(name="setcategory", aliases=["setcat", "sc"])
@commands.has_permissions(administrator=True)
async def tp_setcategory(ctx, ticket_type: str, category: discord.CategoryChannel = None):
    """Set Discord category for a ticket type.
    Usage: $ticket setcategory buy #PURCHASE-TICKET
           $ticket setcategory buy (removes mapping)
    """
    key = ticket_type.lower().replace(" ", "_")
    if key not in TICKET_CATEGORIES:
        cats = ", ".join(f"`{k}`" for k in TICKET_CATEGORIES)
        return await ctx.send(embed=err_embed(f"Ticket type `{ticket_type}` not found.\n\nAvailable types: {cats}"))

    emoji, label, _ = TICKET_CATEGORIES[key]

    if not category:
        TICKET_CATEGORY_MAP.pop(key, None)
        return await ctx.send(embed=ok_embed(f"Removed category mapping for **{emoji} {label}**.\nNew tickets will use the default category."))

    TICKET_CATEGORY_MAP[key] = category.id
    await ctx.send(embed=discord.Embed(
        color=C_SUCCESS,
        description=f"✅ **{emoji} {label}** tickets will now go to **{category.name}**"
    ))


@ticket_prefix.command(name="showcategories", aliases=["showcat", "catmap"])
async def tp_showcategories(ctx):
    """Show all ticket type → Discord category mappings."""
    lines = []
    for key, (emoji, label, _) in TICKET_CATEGORIES.items():
        cat_id = TICKET_CATEGORY_MAP.get(key)
        if cat_id:
            cat = ctx.guild.get_channel(cat_id)
            cat_name = f"**{cat.name}**" if cat else f"~~Deleted~~ ({cat_id})"
        else:
            default_cat = ctx.guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
            cat_name = f"{default_cat.name} *(default)*" if default_cat else "*No category set*"
        lines.append(f"{emoji} **{label}** → {cat_name}")

    e = discord.Embed(
        title="🗂️ Ticket Category Mapping",
        description="\n".join(lines),
        color=C_TICKET
    )
    e.set_footer(text="Use $ticket setcategory <type> #channel to change • Made by Black Belt")
    await ctx.send(embed=e)


@ticket_prefix.command(name="addcat")
@commands.has_permissions(administrator=True)
async def tp_addcat(ctx, emoji: str, *, label: str):
    """Add a ticket category. Usage: $ticket addcat 🎮 Gaming Support"""
    if len(TICKET_CATEGORIES) >= 25:
        return await ctx.send(embed=err_embed("Max 25 categories allowed by Discord."))
    key = label.lower().replace(" ", "_")[:20]
    if key in TICKET_CATEGORIES:
        return await ctx.send(embed=err_embed(f"Category `{label}` already exists."))
    TICKET_CATEGORIES[key] = (emoji, label, "Click on this option to create a ticket")
    e = discord.Embed(
        color=C_SUCCESS,
        description=f"✅ Added category **{emoji} {label}**\nResend the ticket panel with `$ticket panel` to apply."
    )
    await ctx.send(embed=e)

@ticket_prefix.command(name="removecat", aliases=["delcat", "rmcat"])
@commands.has_permissions(administrator=True)
async def tp_removecat(ctx, *, label: str):
    """Remove a ticket category by label. Usage: $ticket removecat Gaming Support"""
    found_key = None
    for key, (emoji, lbl, desc) in TICKET_CATEGORIES.items():
        if lbl.lower() == label.lower() or key.lower() == label.lower():
            found_key = key
            break
    if not found_key:
        cats = ", ".join(f"`{lbl}`" for _, (_, lbl, _) in TICKET_CATEGORIES.items())
        return await ctx.send(embed=err_embed(f"Category not found.\n\nAvailable: {cats}"))
    emoji, lbl, _ = TICKET_CATEGORIES.pop(found_key)
    e = discord.Embed(
        color=C_SUCCESS,
        description=f"✅ Removed category **{emoji} {lbl}**\nResend the ticket panel with `$ticket panel` to apply."
    )
    await ctx.send(embed=e)

@ticket_prefix.command(name="listcats", aliases=["cats", "categories"])
async def tp_listcats(ctx):
    """List all ticket categories."""
    if not TICKET_CATEGORIES:
        return await ctx.send(embed=err_embed("No categories set."))
    lines = [f"{emoji} **{label}**" for _, (emoji, label, _) in TICKET_CATEGORIES.items()]
    e = discord.Embed(
        title="🎫 Ticket Categories",
        description="\n".join(lines),
        color=C_TICKET
    )
    e.set_footer(text=f"{len(TICKET_CATEGORIES)} categories • Made by Black Belt")
    await ctx.send(embed=e)

@ticket_prefix.command(name="editcat")
@commands.has_permissions(administrator=True)
async def tp_editcat(ctx, emoji: str, old_label: str, *, new_label: str):
    """Edit a category. Usage: $ticket editcat 🎮 OldName New Name"""
    found_key = None
    for key, (em, lbl, desc) in TICKET_CATEGORIES.items():
        if lbl.lower() == old_label.lower() or key.lower() == old_label.lower():
            found_key = key
            break
    if not found_key:
        return await ctx.send(embed=err_embed(f"Category `{old_label}` not found."))
    TICKET_CATEGORIES[found_key] = (emoji, new_label, "Click on this option to create a ticket")
    e = discord.Embed(
        color=C_SUCCESS,
        description=f"✅ Updated to **{emoji} {new_label}**\nResend with `$ticket panel` to apply."
    )
    await ctx.send(embed=e)


# ── !afk ───────────────────────────────────────────────────────────────────────
@bot.command(name="afk")
async def afk_prefix(ctx, *, reason: str = "AFK"):
    afk_map[ctx.author.id] = {"reason": reason, "time": datetime.now(timezone.utc)}
    try:
        nick = ctx.author.nick or ctx.author.name
        if not nick.startswith("[AFK] "):
            await ctx.author.edit(nick=f"[AFK] {nick[:24]}")
    except: pass
    e = discord.Embed(title="💤 AFK Set", description=f"You are now AFK.\n**Reason:** {reason}", color=C_AFK)
    e.set_footer(text="You'll be unset when you send a message. • Made by Black Belt")
    await ctx.send(embed=e)


# ── !timeout / !untimeout ──────────────────────────────────────────────────────
@bot.command(name="timeout")
@commands.has_permissions(moderate_members=True)
async def timeout_prefix(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    td = parse_duration(duration)
    if not td:
        return await ctx.send(embed=err_embed("Invalid duration. Use e.g. `10m`, `1h`, `2d`."))
    if td > timedelta(days=28):
        return await ctx.send(embed=err_embed("Max timeout is 28 days."))
    await member.timeout(datetime.now(timezone.utc) + td, reason=reason)
    e = discord.Embed(title="⏱️ Member Timed Out", color=C_WARN, timestamp=datetime.now(timezone.utc))
    e.add_field(name="Member",    value=f"{member.mention}", inline=True)
    e.add_field(name="Duration",  value=fmt_delta(td),       inline=True)
    e.add_field(name="Reason",    value=reason,              inline=False)
    await ctx.send(embed=e)
    await send_mod_log(ctx.guild, "Timeout", member, member.id, ctx.author, reason, C_WARN)

@bot.command(name="untimeout")
@commands.has_permissions(moderate_members=True)
async def untimeout_prefix(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(embed=ok_embed(f"Removed timeout from {member.mention}."))
    await send_mod_log(ctx.guild, "Un-Timeout", member, member.id, ctx.author, "Manual", C_SUCCESS)


# ── !kick / !ban / !unban ──────────────────────────────────────────────────────
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await member.kick(reason=reason)
    await ctx.send(embed=ok_embed(f"👢 Kicked **{member}** | {reason}"))
    await send_mod_log(ctx.guild, "Kick", member, member.id, ctx.author, reason, C_ERROR)

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban_prefix(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(embed=ok_embed(f"🔨 Banned **{member}** | {reason}"))
    await send_mod_log(ctx.guild, "Ban", member, member.id, ctx.author, reason, C_ERROR)

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban_prefix(ctx, user_id: str):
    try:
        await ctx.guild.unban(discord.Object(int(user_id)))
        await ctx.send(embed=ok_embed(f"Unbanned `{user_id}`."))
        await send_mod_log(ctx.guild, "Unban", user_id, user_id, ctx.author, "Manual", C_SUCCESS)
    except Exception as ex:
        await ctx.send(embed=err_embed(str(ex)))


# ── !warn / !warnings / !clearwarns ───────────────────────────────────────────
@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def warn_prefix(ctx, member: discord.Member, *, reason: str):
    key = (ctx.guild.id, member.id)
    warn_map[key].append({"reason": reason, "mod": str(ctx.author), "time": datetime.now(timezone.utc)})
    count = len(warn_map[key])
    e = discord.Embed(title="⚠️ Warning Issued", color=C_WARN, timestamp=datetime.now(timezone.utc))
    e.add_field(name="User",   value=member.mention, inline=True)
    e.add_field(name="Warn #", value=str(count),     inline=True)
    e.add_field(name="Reason", value=reason,         inline=False)
    try: await member.send(embed=e)
    except: pass
    await ctx.send(embed=e)
    await send_mod_log(ctx.guild, "Warn", member, member.id, ctx.author, reason, C_WARN)

@bot.command(name="warnings")
@commands.has_permissions(moderate_members=True)
async def warnings_prefix(ctx, member: discord.Member):
    key   = (ctx.guild.id, member.id)
    warns = warn_map.get(key, [])
    if not warns:
        return await ctx.send(embed=ok_embed(f"{member} has no warnings."))
    lines = "\n\n".join(
        f"**#{i+1}** — {w['reason']}\n> by {w['mod']} • <t:{int(w['time'].timestamp())}:R>"
        for i, w in enumerate(warns))
    e = discord.Embed(title=f"⚠️ Warnings for {member}", description=lines, color=C_WARN)
    e.set_footer(text=f"Total: {len(warns)} • Made by Black Belt")
    await ctx.send(embed=e)

@bot.command(name="clearwarns")
@commands.has_permissions(administrator=True)
async def clearwarns_prefix(ctx, member: discord.Member):
    warn_map.pop((ctx.guild.id, member.id), None)
    await ctx.send(embed=ok_embed(f"Cleared all warnings for {member.mention}."))


# ── !purge ────────────────────────────────────────────────────────────────────
@bot.command(name="purge", aliases=["clear", "prune"])
@commands.has_permissions(manage_messages=True)
async def purge_prefix(ctx, amount: int = 10, member: discord.Member = None):
    await ctx.message.delete()
    amount = max(1, min(amount, 100))
    def check(m):
        if member:
            return m.author == member
        return True
    try:
        deleted = await ctx.channel.purge(limit=amount, check=check, bulk=True)
        msg = await ctx.send(embed=ok_embed(f"Deleted **{len(deleted)}** message(s)."))
        await asyncio.sleep(4)
        await msg.delete()
    except Exception as ex:
        await ctx.send(embed=err_embed(f"Purge failed: {ex}"), delete_after=5)


# ── !lock / !unlock ───────────────────────────────────────────────────────────
@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock_prefix(ctx, channel: discord.TextChannel = None):
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=False)
    e = discord.Embed(description=f"🔒 {ch.mention} has been **locked**.", color=C_ERROR)
    await ctx.send(embed=e)

@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock_prefix(ctx, channel: discord.TextChannel = None):
    ch = channel or ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=None)
    e = discord.Embed(description=f"🔓 {ch.mention} has been **unlocked**.", color=C_SUCCESS)
    await ctx.send(embed=e)


# ── !slowmode ─────────────────────────────────────────────────────────────────
@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode_prefix(ctx, seconds: int, channel: discord.TextChannel = None):
    ch = channel or ctx.channel
    await ch.edit(slowmode_delay=max(0, min(seconds, 21600)))
    msg = f"Slowmode disabled in {ch.mention}." if seconds == 0 else f"Slowmode set to **{seconds}s** in {ch.mention}."
    await ctx.send(embed=ok_embed(msg))


# ── !note ─────────────────────────────────────────────────────────────────────
@bot.command(name="note")
@commands.has_permissions(moderate_members=True)
async def note_prefix(ctx, member: discord.Member, *, text: str = None):
    key = (ctx.guild.id, member.id)
    if not text:
        notes = note_map.get(key, [])
        if not notes:
            return await ctx.send(embed=ok_embed(f"No notes for {member}."))
        lines = "\n\n".join(
            f"**#{i+1}** — {n['text']}\n> by {n['mod']} • <t:{int(n['time'].timestamp())}:R>"
            for i, n in enumerate(notes))
        return await ctx.send(embed=discord.Embed(title=f"📝 Notes for {member}", description=lines, color=C_INFO))
    note_map[key].append({"text": text, "mod": str(ctx.author), "time": datetime.now(timezone.utc)})
    await ctx.send(embed=ok_embed(f"Note added for {member.mention}."))


# ── !invites / !inviteboard / !resetinvites ───────────────────────────────────
@bot.command(name="invites", aliases=["i", "inv", "invite"])
async def invites_prefix(ctx, member: discord.Member = None):
    target   = member or ctx.author
    data     = invite_tracker[ctx.guild.id][target.id]
    total    = data["invites"]
    joins    = data["invites"] + data["rejoins"]
    left     = data["left"]
    fake     = data["fake"]
    rejoins  = data["rejoins"]
    time_str = datetime.now().strftime("%H:%M")

    inv_word = "invites" if total != 1 else "invite"
    e = discord.Embed(color=0x3498db)
    e.set_author(name="Invite log")
    e.set_thumbnail(url=target.display_avatar.url)
    e.description = (
        f"\u25b6\u25b6 **{target.display_name} has {total} {inv_word}**\n\n"
        f"**Joins :** {joins}\n"
        f"**Left :** {left}\n"
        f"**Fake :** {fake}\n"
        f"**Rejoins :** {rejoins}"
    )
    e.set_footer(text=f"Requested by {ctx.author.display_name} \u2022 Today at {time_str} • Made by Black Belt")
    await ctx.send(embed=e)

@bot.command(name="inviteboard", aliases=["lb", "leaderboard", "ilb"])
async def inviteboard_prefix(ctx):
    gdata = invite_tracker.get(ctx.guild.id, {})
    sorted_data = sorted(gdata.items(), key=lambda x: x[1]["invites"], reverse=True)
    if not sorted_data:
        return await ctx.send(embed=err_embed("No invite data yet."))

    PER_PAGE = 10
    total_pages = max(1, (len(sorted_data) + PER_PAGE - 1) // PER_PAGE)

    def make_embed(page: int) -> discord.Embed:
        start = page * PER_PAGE
        chunk = sorted_data[start:start + PER_PAGE]
        lines = []
        for idx, (uid, d) in enumerate(chunk):
            rank    = start + idx + 1
            total   = d["invites"]
            joins   = d["invites"] + d["rejoins"]
            left    = d["left"]
            fake    = d["fake"]
            rejoins = d["rejoins"]
            lines.append(
                f"**#{rank}** <@{uid}> • **{total} Invite{'s' if total != 1 else ''}** "
                f"(**{joins}** Joins, **{left}** Leaves, **{fake}** Fakes, **{rejoins}** Rejoins)"
            )
        e = discord.Embed(color=0x2b2d31, timestamp=datetime.now(timezone.utc))
        e.set_author(name="Invite Leaderboard")
        e.description = "\n".join(lines)
        e.set_footer(text=f"Page {page+1}/{total_pages} | {len(sorted_data)} members tracked • Made by Black Belt")
        return e

    class LeaderboardView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.page = 0
            self.update_buttons()

        def update_buttons(self):
            self.first_btn.disabled  = self.page == 0
            self.prev_btn.disabled   = self.page == 0
            self.next_btn.disabled   = self.page >= total_pages - 1
            self.last_btn.disabled   = self.page >= total_pages - 1

        @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="lb_first")
        async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = 0
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="lb_prev")
        async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = max(0, self.page - 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.primary, custom_id="lb_stop")
        async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()

        @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="lb_next")
        async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = min(total_pages - 1, self.page + 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="lb_last")
        async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = total_pages - 1
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    view = LeaderboardView()
    await ctx.send(embed=make_embed(0), view=view)

@bot.command(name="resetinvites")
@commands.has_permissions(administrator=True)
async def resetinvites_prefix(ctx, member: discord.Member):
    invite_tracker[ctx.guild.id].pop(member.id, None)
    await ctx.send(embed=ok_embed(f"Reset invite count for {member.mention}."))


# ── !userinfo / !serverinfo / !avatar / !ping / !botinfo ─────────────────────
@bot.command(name="userinfo")
async def userinfo_prefix(ctx, member: discord.Member = None):
    target = member or ctx.author
    roles  = [r.mention for r in target.roles if r != ctx.guild.default_role]
    e = discord.Embed(title=f"👤 {target}", color=C_PRIMARY, timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="ID",              value=str(target.id), inline=True)
    e.add_field(name="Bot",             value="Yes" if target.bot else "No", inline=True)
    e.add_field(name="Account Created", value=f"<t:{int(target.created_at.timestamp())}:R>", inline=True)
    e.add_field(name="Joined Server",   value=f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "N/A", inline=True)
    e.add_field(name="Roles",           value=" ".join(roles) if roles else "None", inline=False)
    await ctx.send(embed=e)

@bot.command(name="serverinfo")
async def serverinfo_prefix(ctx):
    g = ctx.guild
    e = discord.Embed(title=f"🏠 {g.name}", color=C_PRIMARY, timestamp=datetime.now(timezone.utc))
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Owner",        value=f"<@{g.owner_id}>",                inline=True)
    e.add_field(name="Members",      value=str(g.member_count),               inline=True)
    e.add_field(name="Channels",     value=str(len(g.channels)),              inline=True)
    e.add_field(name="Roles",        value=str(len(g.roles)),                 inline=True)
    e.add_field(name="Boosts",       value=str(g.premium_subscription_count), inline=True)
    e.add_field(name="Created",      value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
    await ctx.send(embed=e)

@bot.command(name="avatar")
async def avatar_prefix(ctx, member: discord.Member = None):
    target = member or ctx.author
    e = discord.Embed(title=f"🖼️ {target.display_name}'s Avatar", color=C_PRIMARY)
    e.set_image(url=target.display_avatar.replace(size=1024).url)
    await ctx.send(embed=e)

@bot.command(name="ping")
async def ping_prefix(ctx):
    latency = round(bot.latency * 1000)
    e = discord.Embed(title="🏓 Pong!", color=C_INFO)
    e.add_field(name="Bot Latency", value=f"{latency}ms", inline=True)
    await ctx.send(embed=e)

@bot.command(name="botinfo")
async def botinfo_prefix(ctx):
    e = discord.Embed(
        title=f"🤖 {BOT_NAME} Bot",
        description="Full-featured Discord bot — Tickets, Mod, AFK, Invites & more.",
        color=C_PRIMARY, timestamp=datetime.now(timezone.utc)
    )
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name="📋 Features", value=(
        "🎫 Tickets · ⏱️ Timeout · 💤 AFK\n"
        "📨 Invite Tracking · ⚠️ Warns\n"
        "🔒 Lock/Unlock · 🗑️ Purge · 🔇 Slowmode\n"
        "📝 Notes · 📊 Userinfo/Serverinfo"
    ), inline=False)
    e.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    e.add_field(name="Prefix",  value="!",                  inline=True)
    await ctx.send(embed=e)


# ── Prefix error handler ──────────────────────────────────────────────────────
# ── $setfakedays ─────────────────────────────────────────────────────────────
@bot.command(name="setfakedays", aliases=["fakedays"])
@commands.has_permissions(administrator=True)
async def setfakedays_cmd(ctx, days: int):
    global FAKE_DAYS
    if days < 0 or days > 365:
        return await ctx.send(embed=err_embed("Days must be between 0 and 365."))
    FAKE_DAYS = days
    e = discord.Embed(
        color=C_SUCCESS,
        description=(
            f"✅ Fake detection updated!\n\n"
            f"Accounts newer than **{days} days** will be counted as **Fake**.\n"
            f"Use `$setfakedays 0` to disable fake detection."
        )
    )
    await ctx.send(embed=e)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=err_embed("You don't have permission for this command."), delete_after=5)
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=err_embed(f"I am missing permissions: `{error.missing_permissions}`"), delete_after=5)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=err_embed("Member not found. Try mentioning them or use their ID."), delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=err_embed(f"Invalid argument. Check `$help` for usage."), delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=err_embed(f"Missing: `{error.param.name}` — check `$help` for usage."), delete_after=5)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(embed=err_embed(f"Cooldown! Try again in `{error.retry_after:.1f}s`."), delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=err_embed("You don't have permission to use this command."), delete_after=5)
    else:
        await ctx.send(embed=err_embed(f"Error: {str(error)}"), delete_after=8)



# ═══════════════════════════════════════════════════════════════════════════════
#  MEMBER COUNT
# ═══════════════════════════════════════════════════════════════════════════════

@bot.command(name="mc", aliases=["membercount", "members"])
async def mc_cmd(ctx):
    g = ctx.guild
    total   = g.member_count
    humans  = sum(1 for m in g.members if not m.bot)
    bots    = sum(1 for m in g.members if m.bot)
    online  = sum(1 for m in g.members if m.status != discord.Status.offline and not m.bot)

    e = discord.Embed(color=0x5865f2)
    e.description = f"**{g.name}**\n__Total members__ : {total}"
    await ctx.send(embed=e)


# ═══════════════════════════════════════════════════════════════════════════════
#  GIVEAWAY SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

giveaway_store = {}   # msg_id → {channel_id, prize, winners, end_time, host_id, ended}

@bot.command(name="gstart", aliases=["gcreate"])
@commands.has_permissions(manage_guild=True)
async def gstart_cmd(ctx, duration: str, winners: int, *, prize: str):
    td = parse_duration(duration)
    if not td:
        return await ctx.send(embed=err_embed("Invalid duration. Use e.g. `1h`, `30m`, `1d`."))
    if winners < 1:
        return await ctx.send(embed=err_embed("Winners must be at least 1."))

    end_time  = datetime.now(timezone.utc) + td
    end_ts    = int(end_time.timestamp())
    dur_label = fmt_delta(td)

    e = discord.Embed(
        title=f"🎁 {prize} 🎁",
        color=discord.Color.gold(),
        timestamp=end_time
    )
    e.description = (
        f"\u2022 **Winners:** {winners}\n"
        f"\u2022 **Ends:** in {dur_label} (<t:{end_ts}:F>)\n"
        f"\u2022 **Hosted by:** {ctx.author.mention}\n\n"
        f"\u2022 React with 🎉 to participate!"
    )
    # Discord auto-updates <t:ts:R> as live countdown
    e.set_footer(text=f"Ends at • Today at {end_time.strftime('%H:%M')} • Made by Black Belt")
    e.add_field(name="⏳ Time Remaining", value=f"<t:{end_ts}:R>", inline=False)

    await ctx.message.delete()
    msg = await ctx.send(content="🎊 **New Giveaway** 🎊", embed=e)
    await msg.add_reaction("🎉")

    giveaway_store[msg.id] = {
        "channel_id": ctx.channel.id,
        "prize":      prize,
        "winners":    winners,
        "end_time":   end_time,
        "host_id":    ctx.author.id,
        "ended":      False,
        "msg_id":     msg.id
    }

    # Auto-end after duration
    async def auto_end():
        await asyncio.sleep(td.total_seconds())
        await _end_giveaway(msg.id, ctx.guild)

    bot.loop.create_task(auto_end())


async def _end_giveaway(msg_id: int, guild: discord.Guild):
    data = giveaway_store.get(msg_id)
    if not data or data["ended"]:
        return
    data["ended"] = True

    ch = guild.get_channel(data["channel_id"])
    if not ch:
        return
    try:
        msg = await ch.fetch_message(msg_id)
    except:
        return

    # Collect reactors
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if reaction:
        users = [u async for u in reaction.users() if not u.bot]
    else:
        users = []

    prize    = data["prize"]
    n_win    = data["winners"]
    host     = guild.get_member(data["host_id"])
    host_str = host.mention if host else "Unknown"

    import random
    ended_at = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M")

    if not users:
        e = discord.Embed(
            title=f"🎁 {prize} 🎁",
            color=discord.Color.red()
        )
        e.description = (
            f"\u2022 **Hosted by:** {host_str}\n"
            f"\u2022 **Total participant(s):** 0\n"
            f"\u2022 **Winner :**\nNo valid entries."
        )
        e.set_footer(text=f"Ended \u2022 {ended_at} • Made by Black Belt")
    else:
        chosen = random.sample(users, min(n_win, len(users)))
        winners_str = "\n".join(w.mention for w in chosen)
        winners_announce = ", ".join(w.mention for w in chosen)
        e = discord.Embed(
            title=f"🎁 {prize} 🎁",
            color=discord.Color.gold()
        )
        e.description = (
            f"\u2022 **Hosted by:** {host_str}\n"
            f"\u2022 **Total participant(s):** {len(users)}\n"
            f"\u2022 **Winner :**\n{winners_str}"
        )
        e.set_footer(text=f"Ended \u2022 {ended_at} • Made by Black Belt")
        await ch.send(
            f"Congrats, {winners_announce} you have won **{prize}**, hosted by {host_str}"
        )

    await msg.edit(content="🎊 **Giveaway Ended** 🎊", embed=e)


@bot.command(name="gend")
@commands.has_permissions(manage_guild=True)
async def gend_cmd(ctx, msg_id: int):
    if msg_id not in giveaway_store:
        return await ctx.send(embed=err_embed("Giveaway not found. Check the message ID."))
    await _end_giveaway(msg_id, ctx.guild)
    await ctx.send(embed=ok_embed("Giveaway ended!"), delete_after=5)


@bot.command(name="greroll")
@commands.has_permissions(manage_guild=True)
async def greroll_cmd(ctx, msg_id: int):
    data = giveaway_store.get(msg_id)
    if not data:
        return await ctx.send(embed=err_embed("Giveaway not found. Check the message ID."))

    ch = ctx.guild.get_channel(data["channel_id"])
    try:
        msg = await ch.fetch_message(msg_id)
    except:
        return await ctx.send(embed=err_embed("Could not fetch giveaway message."))

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if reaction:
        users = [u async for u in reaction.users() if not u.bot]
    else:
        users = []

    if not users:
        return await ctx.send(embed=err_embed("No valid entries to reroll."))

    import random
    winner = random.choice(users)
    host_member = ctx.guild.get_member(data["host_id"])
    host_str = host_member.mention if host_member else f"<@{data['host_id']}>"
    ended_at = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M")
    prize = data["prize"]

    # Update the giveaway embed with new winner
    e = discord.Embed(
        title=f"🎁 {prize} 🎁",
        color=discord.Color.gold()
    )
    e.description = (
        f"\u2022 **Hosted by:** {host_str}\n"
        f"\u2022 **Total participant(s):** {len(users)}\n"
        f"\u2022 **Winner :**\n{winner.mention}"
    )
    e.set_footer(text=f"Ended \u2022 {ended_at} \u2022 Made by Black Belt")
    await msg.edit(content="🎊 **Giveaway Ended** 🎊", embed=e)

    await ctx.send(f"Congrats, {winner.mention} you have won **{prize}**, hosted by {host_str}")


# ═══════════════════════════════════════════════════════════════════════════════
#  TIMER SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@bot.command(name="tstart", aliases=["timer"])
async def timer_cmd(ctx, duration: str, *, label: str = "Timer"):
    td = parse_duration(duration)
    if not td:
        return await ctx.send(embed=err_embed("Invalid duration. Use e.g. `10m`, `1h`, `2d`."))

    end_time = datetime.now(timezone.utc) + td
    end_ts   = int(end_time.timestamp())
    dur_label = fmt_delta(td)

    e = discord.Embed(color=discord.Color.orange())
    e.title = f"⏱️ Timer ⏱️"
    e.description = (
        f"**{label}**\n\n"
        f"🕐 **Ends :** in {dur_label} (<t:{end_ts}:F>) 🕐"
    )
    e.add_field(name="⏳ Time Remaining", value=f"<t:{end_ts}:R>", inline=False)
    e.set_footer(text=f"Timer ends • Today at {end_time.strftime('%H:%M')} • Made by Black Belt")

    await ctx.message.delete()
    timer_msg = await ctx.send(embed=e)

    async def fire():
        await asyncio.sleep(td.total_seconds())
        done_e = discord.Embed(
            title="✅ Timer Done!",
            description=f"⏰ **{label}** timer has ended!\n{ctx.author.mention}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        await timer_msg.edit(embed=done_e)
        await ctx.send(content=f"⏰ {ctx.author.mention} your **{label}** timer is done!", delete_after=30)

    bot.loop.create_task(fire())



# ═══════════════════════════════════════════════════════════════════════════════
#  ACCOUNT AGE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.command(name="accage", aliases=["accountage", "age"])
async def accage_cmd(ctx, user_id: str = None):
    try:
        if user_id:
            user = await bot.fetch_user(int(user_id))
        else:
            user = ctx.author
    except:
        return await ctx.send(embed=err_embed("User not found. Check the ID."))

    created = user.created_at
    now = datetime.now(timezone.utc)
    diff = now - created

    total_seconds = int(diff.total_seconds())
    years   = diff.days // 365
    months  = (diff.days % 365) // 30
    weeks   = (diff.days % 30) // 7
    days    = (diff.days % 30) % 7
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if years:   parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months:  parts.append(f"{months} month{'s' if months != 1 else ''}")
    if weeks:   parts.append(f"{weeks} week{'s' if weeks != 1 else ''}")
    if days:    parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:   parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes: parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds: parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

    age_str = ", ".join(parts) if parts else "Just created"
    time_str = datetime.now().strftime("%H:%M")

    e = discord.Embed(color=0x5865f2)
    e.title = f"\U0001f4c5 {user.name}'s Account Age"
    e.description = age_str
    e.set_thumbnail(url=user.display_avatar.url)
    e.set_footer(text=f"Requested by {ctx.author.display_name} \u2022 Today at {time_str} \u2022 Made by Black Belt")
    await ctx.send(embed=e)


# ═══════════════════════════════════════════════════════════════════════════════
#  INVITED LIST
# ═══════════════════════════════════════════════════════════════════════════════

@bot.command(name="invited")
async def invited_cmd(ctx, member: discord.Member = None):
    target = member or ctx.author
    guild_data = invite_tracker.get(ctx.guild.id, {})

    # Find all members invited by target
    invited_members = []
    for (guild_id, member_id), inviter_id in member_inviter.items():
        if guild_id == ctx.guild.id and inviter_id == target.id:
            invited_members.append(member_id)

    if not invited_members:
        return await ctx.send(embed=err_embed(f"{target.display_name} has not invited anyone yet."))

    PER_PAGE = 10
    total_pages = max(1, (len(invited_members) + PER_PAGE - 1) // PER_PAGE)
    time_str = datetime.now().strftime("%H:%M")

    def make_embed(page: int) -> discord.Embed:
        start = page * PER_PAGE
        chunk = invited_members[start:start + PER_PAGE]
        lines = []
        for idx, mid in enumerate(chunk):
            rank = start + idx + 1
            badge = f"#{rank}"
            lines.append(f"**{badge}** \u2022 <@{mid}>")

        e = discord.Embed(color=0x5865f2)
        e.title = f"Invited list of {target.display_name}"
        e.description = "\n".join(lines)
        e.set_footer(text=f"Page {page+1}/{total_pages} \u2022 Made by Black Belt")
        return e

    class InvitedView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.page = 0
            self.update_buttons()

        def update_buttons(self):
            self.first_btn.disabled = self.page == 0
            self.prev_btn.disabled  = self.page == 0
            self.next_btn.disabled  = self.page >= total_pages - 1
            self.last_btn.disabled  = self.page >= total_pages - 1

        @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
        async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = 0
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
        async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = max(0, self.page - 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.primary)
        async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()

        @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
        async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = min(total_pages - 1, self.page + 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
        async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = total_pages - 1
            self.update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

    await ctx.send(embed=make_embed(0), view=InvitedView())


# ═══════════════════════════════════════════════════════════════════════════════
#  LOG SETUP COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.command(name="setticketlog")
@commands.has_permissions(administrator=True)
async def setticketlog_cmd(ctx, channel: discord.TextChannel = None):
    global TICKET_LOG_ID
    ch = channel or ctx.channel
    TICKET_LOG_ID = ch.id
    await ctx.send(embed=ok_embed(f"Ticket log channel set to {ch.mention}"))

@bot.command(name="setmodlog")
@commands.has_permissions(administrator=True)
async def setmodlog_cmd(ctx, channel: discord.TextChannel = None):
    global MOD_LOG_ID
    ch = channel or ctx.channel
    MOD_LOG_ID = ch.id
    await ctx.send(embed=ok_embed(f"Mod log channel set to {ch.mention}"))

@bot.command(name="setbotlog")
@commands.has_permissions(administrator=True)
async def setbotlog_cmd(ctx, channel: discord.TextChannel = None):
    global BOT_LOG_ID
    ch = channel or ctx.channel
    BOT_LOG_ID = ch.id
    await ctx.send(embed=ok_embed(f"Bot log channel set to {ch.mention}"))


# ═══════════════════════════════════════════════════════════════════════════════
#  BOT LOG EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def send_bot_log(guild, title, description, color=0x5865f2):
    if not BOT_LOG_ID: return
    ch = guild.get_channel(BOT_LOG_ID)
    if not ch: return
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text="Made by Black Belt")
    try:
        await ch.send(embed=e)
    except: pass

@bot.event
async def on_member_join(member):
    await send_bot_log(member.guild,
        "📥 Member Joined",
        f"{member.mention} **{member}**\nID: `{member.id}`\nAccount: <t:{int(member.created_at.timestamp())}:R>",
        0x57f287)
    # Also handle invite tracking (existing logic below)
    guild = member.guild
    try:
        new_invites = await guild.invites()
        old_cache   = invite_cache.get(guild.id, {})
        used_invite = None
        for inv in new_invites:
            if old_cache.get(inv.code, 0) < inv.uses:
                used_invite = inv
                break
        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
        if used_invite and used_invite.inviter:
            iid      = used_invite.inviter.id
            gkey     = (guild.id, member.id)
            data     = invite_tracker[guild.id][iid]
            account_age_days = (datetime.now(timezone.utc) - member.created_at).days
            is_fake   = (FAKE_DAYS > 0) and (account_age_days < FAKE_DAYS)
            is_rejoin = gkey in member_inviter
            if is_rejoin:
                old_type = member_type.get(gkey, "real")
                if old_type == "real":
                    data["invites"] = max(0, data["invites"] - 1)
                elif old_type == "fake":
                    data["fake"]    = max(0, data["fake"] - 1)
            if is_fake:
                data["fake"]    += 1
            elif is_rejoin:
                data["rejoins"] += 1
            else:
                data["invites"] += 1
            member_inviter[gkey] = iid
            member_type[gkey]    = "fake" if is_fake else ("rejoin" if is_rejoin else "real")
            if INVITE_LOG_ID:
                ch = guild.get_channel(INVITE_LOG_ID)
                if ch:
                    total    = data["invites"]
                    joins    = data["invites"] + data["rejoins"] + data["fake"]
                    inv_word = "invites" if total != 1 else "invite"
                    e = discord.Embed(color=0x2b2d31)
                    e.set_author(name="Invite log")
                    e.set_thumbnail(url=used_invite.inviter.display_avatar.url)
                    e.description = (
                        f"\u25b6\u25b6 **{used_invite.inviter.display_name} has {total} {inv_word}**\n\n"
                        f"**Joins :** {joins}\n"
                        f"**Left :** {data['left']}\n"
                        f"**Fake :** {data['fake']}\n"
                        f"**Rejoins :** {data['rejoins']}"
                    )
                    e.set_footer(text=f"Joined: {member.display_name} \u2022 Today at {datetime.now().strftime('%H:%M')} \u2022 Made by Black Belt")
                    await ch.send(embed=e)
    except: pass

@bot.event
async def on_member_remove(member):
    await send_bot_log(member.guild,
        "📤 Member Left",
        f"{member.mention} **{member}**\nID: `{member.id}`",
        0xed4245)
    guild = member.guild
    gkey  = (guild.id, member.id)
    iid   = member_inviter.get(gkey)
    if iid:
        data  = invite_tracker[guild.id][iid]
        mtype = member_type.get(gkey, "real")
        data["left"] += 1
        if mtype == "real":
            data["invites"] = max(0, data["invites"] - 1)

@bot.event
async def on_member_ban(guild, user):
    await send_bot_log(guild,
        "🔨 Member Banned",
        f"**{user}**\nID: `{user.id}`",
        0xed4245)

@bot.event
async def on_member_unban(guild, user):
    await send_bot_log(guild,
        "✅ Member Unbanned",
        f"**{user}**\nID: `{user.id}`",
        0x57f287)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild or not message.content: return
    await send_bot_log(message.guild,
        "🗑️ Message Deleted",
        f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:**\n{message.content[:500]}",
        0xfee75c)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild: return
    if before.content == after.content: return
    await send_bot_log(before.guild,
        "✏️ Message Edited",
        f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n**Before:** {before.content[:300]}\n**After:** {after.content[:300]}",
        0x5865f2)



# ═══════════════════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        print("❌  BOT_TOKEN not set in .env file!")
        exit(1)
    bot.run(TOKEN)
