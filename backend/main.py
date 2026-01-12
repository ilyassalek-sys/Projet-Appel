import os
from fastapi import FastAPI, Request
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import dateparser
import pytz

load_dotenv()

db: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
app = FastAPI()

paris_tz = pytz.timezone("Europe/Paris")

@app.get("/")
def home():
    return {"status": "online"}

# --- OUTIL 1 : CRÉATION ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    try:
        payload = await request.json()
        args = payload.get('arguments') or payload
        now_paris = datetime.now(paris_tz)

        parsed_date = dateparser.parse(
            args.get('time_str'), 
            settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': now_paris.replace(tzinfo=None), 'DATE_ORDER': 'DMY'}
        )

        if not parsed_date:
            return {"result": "Je n'ai pas compris la date."}
        
        parsed_date = paris_tz.localize(parsed_date)
        formatted_time = parsed_date.strftime("%Y-%m-%d %H:%M:%S")

        customer_phone = args.get('phone_backup') or payload.get('customer', {}).get('number')
        resto_resp = db.table('restaurants').select("id").limit(1).execute()
        restaurant_id = resto_resp.data[0]['id']

        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_phone": str(customer_phone),
            "customer_name": args.get('name'),
            "party_size": int(args.get('size')),
            "reservation_time": formatted_time,
            "status": "confirmed"
        }).execute()
        
        return {"result": f"C'est réservé pour le {parsed_date.strftime('%d/%m à %H:%M')}."}
    except Exception as e:
        return {"result": f"Erreur : {str(e)}"}

# --- OUTIL 2 : MODIFICATION / ANNULATION (VERSION ROBUSTE) ---
@app.post("/tools/manage_reservation")
async def manage_reservation(request: Request):
    try:
        payload = await request.json()
        args = payload.get('arguments') or payload
        
        name = args.get('name')
        phone = args.get('phone')
        action = args.get('action') # 'cancel' ou 'update'
        new_size = args.get('new_size')

        # 1. Recherche de la réservation active
        query = db.table('reservations').select("*").ilike('customer_name', f"%{name}%").eq('status', 'confirmed')
        
        if phone:
            query = query.eq('customer_phone', str(phone))
            
        res = query.execute()

        # 2. Gestion des cas particuliers
        if len(res.data) == 0:
            return {"result": f"Je ne trouve aucune réservation confirmée au nom de {name}."}
        
        if len(res.data) > 1 and not phone:
            return {"result": f"Il y a plusieurs réservations pour {name}. J'ai besoin du numéro de téléphone pour identifier la bonne."}

        reservation_id = res.data[0]['id']

        # 3. Actions réelles sur la base
        if action == "cancel":
            db.table('reservations').update({"status": "cancelled"}).eq('id', reservation_id).execute()
            return {"result": f"C'est fait, la réservation de {name} est annulée."}
        
        if action == "update":
            if new_size:
                # Mise à jour de party_size dans Supabase
                db.table('reservations').update({"party_size": int(new_size)}).eq('id', reservation_id).execute()
                return {"result": f"C'est modifié ! La réservation de {name} est passée à {new_size} personnes."}
            else:
                return {"result": "D'accord, quel est le nouveau nombre de personnes ?"}

        return {"result": f"J'ai bien trouvé la réservation de {name}. Voulez-vous la modifier (nombre de personnes) ou l'annuler ?"}

    except Exception as e:
        return {"result": f"Erreur technique : {str(e)}"}