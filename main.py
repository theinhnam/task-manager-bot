import discord
from discord.ext import commands
from database import Session, Project, Task
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pandas as pd
import os
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# --- Cấu hình Timezone Việt Nam (UTC+7) ---
VIETNAM_TZ = timezone(timedelta(hours=7))

# --- Bot Setup ---
intents = discord.Intents.default()
intents.messages = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
scheduler = AsyncIOScheduler(timezone=str(VIETNAM_TZ))

# --- Helper Functions ---
def to_vietnam_time(utc_dt):
    return utc_dt.astimezone(VIETNAM_TZ) if utc_dt else None

def parse_custom_time(time_str):
    """Xử lý các định dạng thời gian phổ biến của người Việt"""
    now = datetime.now(VIETNAM_TZ)
    
    # Xử lý giờ đơn giản: 14h, 14h30, 14:30
    if re.match(r"^\d{1,2}h?\d*$", time_str):
        time_str = time_str.replace('h', ':').replace(' ', '')
        if ':' not in time_str:
            time_str += ':00'
    
    try:
        # Thử định dạng HH:MM
        if re.match(r"^\d{1,2}:\d{2}$", time_str):
            hours, minutes = map(int, time_str.split(':'))
            return now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        
        # Thử định dạng dd/mm HH:MM
        if re.match(r"^\d{1,2}/\d{1,2} \d{1,2}:\d{2}$", time_str):
            date_part, time_part = time_str.split(' ')
            day, month = map(int, date_part.split('/'))
            hours, minutes = map(int, time_part.split(':'))
            return now.replace(day=day, month=month, hour=hours, minute=minutes, second=0, microsecond=0)
        
        # Thử định dạng dd/mm
        if re.match(r"^\d{1,2}/\d{1,2}$", time_str):
            day, month = map(int, time_str.split('/'))
            return now.replace(day=day, month=month, hour=12, minute=0, second=0, microsecond=0)
        
    except ValueError:
        return None
    
    return None

def create_item_embed(item, title):
    """Tạo embed cho cả task và note"""
    embed = discord.Embed(title=title, color=0x3498db)
    
    if item.due_date:
        due_vn = to_vietnam_time(item.due_date)
        time_info = f"⏰ {due_vn.strftime('%d/%m %H:%M')}"
    else:
        time_info = "📝 Ghi chú"
    
    embed.add_field(name="Dự án", value=item.project_name, inline=True)
    embed.add_field(name="Loại", value=time_info, inline=True)
    embed.add_field(name="Nội dung", value=item.content, inline=False)
    
    return embed

# --- Bot Commands ---
@bot.command()
async def helpme(ctx):
    """Gửi hướng dẫn sử dụng"""
    embed = discord.Embed(title="📝 TaskMaster Bot Help", color=0x2ecc71)
    commands_list = [
        ("!project <tên>", "Tạo dự án mới"),
        ("!add <dự án> <thời gian?> <nội dung>", "Thêm task/note (nhiều mục cách nhau bằng dòng)"),
        ("!today", "Xem task hôm nay"),
        ("!notes", "Xem tất cả ghi chú"),
        ("!list <dự án>", "Xem tất cả task/note của dự án"),
        ("!export <dự án>", "Xuất ra Excel")
    ]
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.set_footer(text="📌 Cách nhập thời gian: 14h, 14h30, 14:30, 15/12, 15/12 14h30")
    await ctx.send(embed=embed)

@bot.command()
async def project(ctx, name):
    """Tạo dự án mới"""
    session = Session()
    try:
        project = Project(name=name, user_id=str(ctx.author.id))
        session.add(project)
        session.commit()
        await ctx.send(f"✅ Đã tạo dự án **{name}**!")
    finally:
        session.close()

@bot.command()
async def add(ctx, project_name, *, content):
    """
    Thêm task/note vào dự án
    Cách sử dụng:
    !add DựánA
    Nội dung 1 @ 14h30
    Nội dung 2
    Nội dung 3 @ 15/12
    """
    session = Session()
    try:
        items = []
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Tách thời gian nếu có (sử dụng @ để đánh dấu)
            time_match = re.search(r'@\s*(.+)$', line)
            due_date = None
            
            if time_match:
                time_str = time_match.group(1).strip()
                line = re.sub(r'@\s*.+$', '', line).strip()
                due_date = parse_custom_time(time_str)
                
                if not due_date:
                    await ctx.send(f"⚠️ Định dạng thời gian không hợp lệ: `{time_str}`. Sử dụng: 14h30, 15/12, 15/12 14h30")
                    continue
            
            # Tạo task/note mới
            item = Task(
                project_name=project_name,
                content=line,
                due_date=due_date,
                user_id=str(ctx.author.id)
            )
            session.add(item)
            items.append(item)
        
        session.commit()
        
        # Lên lịch thông báo cho các task có thời hạn
        for item in items:
            if item.due_date:
                scheduler.add_job(
                    notify_user,
                    'date',
                    run_date=item.due_date - timedelta(minutes=10),
                    args=[ctx.author.id, item.id, "⏰ Task sắp đến hạn (10 phút)"]
                )
                scheduler.add_job(
                    notify_user,
                    'date',
                    run_date=item.due_date,
                    args=[ctx.author.id, item.id, "🔔 Task đến hạn!"]
                )
        
        await ctx.send(f"✅ Đã thêm {len(items)} mục vào **{project_name}**!")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {str(e)}")
    finally:
        session.close()

# --- Notification Handler ---
async def notify_user(user_id, task_id, message):
    user = await bot.fetch_user(user_id)
    session = Session()
    try:
        task = session.query(Task).get(task_id)
        if task:
            embed = create_item_embed(task, message)
            await user.send(embed=embed)
            
            # Đánh dấu đã thông báo
            if "10 minutes" in message:
                task.notified_10min = True
            else:
                task.notified_due = True
            session.commit()
    finally:
        session.close()

# --- Task/Note Listing ---
@bot.command()
async def today(ctx):
    """Hiển thị task hôm nay"""
    session = Session()
    try:
        now = datetime.now(VIETNAM_TZ)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        tasks = session.query(Task).filter(
            Task.user_id == str(ctx.author.id),
            Task.due_date >= start,
            Task.due_date <= end
        ).all()
        
        if not tasks:
            await ctx.send("🎉 Bạn không có task nào hôm nay!")
            return
        
        embed = discord.Embed(
            title=f"📅 Task Hôm Nay ({now.strftime('%d/%m')})",
            color=0x3498db
        )
        
        for task in tasks:
            due_vn = to_vietnam_time(task.due_date)
            time_str = due_vn.strftime("%H:%M")
            embed.add_field(
                name=f"{task.project_name} - {time_str}",
                value=task.content,
                inline=False
            )
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command()
async def notes(ctx):
    """Hiển thị tất cả ghi chú"""
    session = Session()
    try:
        notes = session.query(Task).filter(
            Task.user_id == str(ctx.author.id),
            Task.due_date.is_(None)
        ).all()
        
        if not notes:
            await ctx.send("📭 Bạn chưa có ghi chú nào!")
            return
        
        embed = discord.Embed(
            title="📝 Tất Cả Ghi Chú",
            color=0xffcc00
        )
        
        for note in notes:
            embed.add_field(
                name=f"{note.project_name}",
                value=note.content,
                inline=False
            )
        
        await ctx.send(embed=embed)
    finally:
        session.close()

@bot.command()
async def list(ctx, project_name):
    """Liệt kê tất cả task/note trong dự án"""
    session = Session()
    try:
        items = session.query(Task).filter(
            Task.user_id == str(ctx.author.id),
            Task.project_name == project_name
        ).order_by(Task.due_date.asc()).all()
        
        if not items:
            await ctx.send(f"📭 Không có mục nào trong **{project_name}**!")
            return
        
        embed = discord.Embed(
            title=f"📋 Tất Cả Mục Trong {project_name}",
            color=0x9b59b6
        )
        
        for item in items:
            if item.due_date:
                due_vn = to_vietnam_time(item.due_date)
                time_info = f"⏰ {due_vn.strftime('%d/%m %H:%M')}"
            else:
                time_info = "📝 Ghi chú"
            
            embed.add_field(
                name=time_info,
                value=item.content,
                inline=False
            )
        
        await ctx.send(embed=embed)
    finally:
        session.close()

# --- Excel Export ---
@bot.command()
async def export(ctx, project_name):
    """Xuất task/note ra Excel"""
    session = Session()
    try:
        items = session.query(Task).filter(
            Task.user_id == str(ctx.author.id),
            Task.project_name == project_name
        ).all()
        
        if not items:
            await ctx.send(f"📭 Không có mục nào trong **{project_name}**!")
            return
        
        # Chuẩn bị dữ liệu
        data = []
        for item in items:
            if item.due_date:
                due_vn = to_vietnam_time(item.due_date)
                due_str = due_vn.strftime("%d/%m/%Y %H:%M")
                item_type = "Task"
            else:
                due_str = "N/A"
                item_type = "Note"
            
            data.append({
                "Dự án": item.project_name,
                "Loại": item_type,
                "Nội dung": item.content,
                "Hạn chót": due_str
            })
        
        # Tạo DataFrame
        df = pd.DataFrame(data)
        
        # Xuất Excel
        filename = f"{project_name}_tasks_notes.xlsx"
        df.to_excel(filename, index=False)
        
        # Gửi file
        await ctx.send(file=discord.File(filename))
        os.remove(filename)
        
    except Exception as e:
        await ctx.send(f"❌ Lỗi khi xuất file: {str(e)}")
    finally:
        session.close()

# --- Security ---
@bot.check
async def dm_only(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("❌ Vui lòng chỉ sử dụng bot qua tin nhắn riêng (DM)!")
        return False
    return True

# --- Startup ---
@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {bot.user.name}")
    scheduler.start()

if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_TOKEN'))