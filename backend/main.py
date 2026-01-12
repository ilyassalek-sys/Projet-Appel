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

# --- OUTIL 2 : MODIFICATION (FIXÉ) ---
@app.post("/tools/manage_reservation")
async def manage_reservation(request: Request):
    try:
        payload = await request.json()
        args = payload.get('arguments') or payload
        
        name = args.get('name')
        phone = args.get('phone')
        action = args.get('action') # 'cancel' ou 'update'
        new_size = args.get('new_size')
        new_time_str = args.get('new_time')

        # 1. Recherche de la réservation
        query = db.table('reservations').select("*").ilike('customer_name', f"%{name}%").eq('status', 'confirmed')
        if phone:
            query = query.eq('customer_phone', str(phone))
        res = query.execute()

        if len(res.data) == 0:
            return {"result": f"Aucune réservation trouvée pour {name}."}
        
        if len(res.data) > 1 and not phone:
            return {"result": "Plusieurs réservations trouvées. J'ai besoin de votre numéro."}

        reservation_id = res.data[0]['id']

        # 2. Logique de mise à jour (Correction : On ne bloque plus si new_size est vide)
        if action == "update":
            update_data = {}
            
            # Changement de taille
            if new_size:
                update_data["party_size"] = int(new_size)
            
            # Changement de date
            if new_time_str:
                now_paris = datetime.now(paris_tz)
                parsed_new_date = dateparser.parse(
                    new_time_str, 
                    settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': now_paris.replace(tzinfo=None), 'DATE_ORDER': 'DMY'}
                )
                if parsed_new_date:
                    parsed_new_date = paris_tz.localize(parsed_new_date)
                    update_data["reservation_time"] = parsed_new_date.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    return {"result": "Je n'ai pas compris le nouvel horaire."}

            # On vérifie si on a au moins une modification à faire
            if update_data:
                db.table('reservations').update(update_data).eq('id', reservation_id).execute()
                return {"result": "Mise à jour effectuée avec succès dans la base de données."}
            else:
                return {"result": "D'accord, mais que voulez-vous modifier ? (Heure ou nombre de personnes)"}

        if action == "cancel":
            db.table('reservations').update({"status": "cancelled"}).eq('id', reservation_id).execute()
            return {"result": f"La réservation de {name} est annulée."}

        return {"result": "Voulez-vous modifier l'heure, le nombre de personnes ou annuler ?"}

    except Exception as e:
        return {"result": f"Erreur : {str(e)}"}