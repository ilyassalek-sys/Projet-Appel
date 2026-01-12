import os
from fastapi import FastAPI, Request
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import dateparser

load_dotenv()

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

@app.get("/")
def home():
    return {"status": "online"}

# --- ROUTE 1 : INITIALISATION ---
@app.post("/call/init")
async def init_call(request: Request):
    payload = await request.json()
    called_number = payload.get('message', {}).get('phone_number', {}).get('number') or '+12406509923'
    
    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    if not response.data:
        return {"assistant": {"firstMessage": "Restaurant non trouvé."}}
    
    resto = response.data[0]

    return {
        "assistant": {
            "firstMessage": f"Bienvenue chez {resto['name']} ! Pour combien de personnes souhaitez-vous réserver ?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "systemPrompt": f"Tu es l'assistant de {resto['name']}. Demande le nom, le nombre de personnes et l'heure. Si le numéro manque, demande-le."
            }
        }
    }

# --- ROUTE 2 : BOOK TABLE (CORRIGÉE) ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    try:
        payload = await request.json()
        print(f"DEBUG Payload reçu: {payload}")

        # Extraction des arguments (API Request format)
        args = payload.get('arguments') or payload
        if 'message' in payload and not args.get('name'):
            tool_call = payload.get('message', {}).get('toolCalls', [{}])[0]
            args = tool_call.get('function', {}).get('arguments', {})

        # 1. Récupération du numéro de téléphone
        customer_phone = (
            args.get('phone_backup') or 
            payload.get('customer', {}).get('number') or
            payload.get('message', {}).get('call', {}).get('customer', {}).get('number')
        )
        
        if not customer_phone:
            return {"result": "Il me manque votre numéro de téléphone."}

        # 2. Formatage de la date
        parsed_date = dateparser.parse(args.get('time_str'), settings={'PREFER_DATES_FROM': 'future'})
        if not parsed_date:
            return {"result": "Je n'ai pas compris la date."}
        
        formatted_time = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
        
        # Pour l'anti-spam, on définit le début et la fin de la journée
        start_day = parsed_date.strftime("%Y-%m-%d 00:00:00")
        end_day = parsed_date.strftime("%Y-%m-%d 23:59:59")

        # 3. Récupération Restaurant ID
        resto_resp = db.table('restaurants').select("id").limit(1).execute()
        restaurant_id = resto_resp.data[0]['id']

        # 4. VÉRIFICATION ANTI-SPAM (Correction du filtre de date)
        # On utilise gte (greater than or equal) et lte (less than or equal)
        existing_res = db.table('reservations') \
            .select("id", count="exact") \
            .eq('customer_phone', str(customer_phone)) \
            .gte('reservation_time', start_day) \
            .lte('reservation_time', end_day) \
            .execute()

        if existing_res.count and existing_res.count >= 2:
            return {"result": "Désolé, vous avez déjà 2 réservations pour cette journée."}

        # 5. INSERTION
        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_phone": str(customer_phone),
            "customer_name": args.get('name'),
            "party_size": int(args.get('size')),
            "reservation_time": formatted_time,
            "status": "confirmed"
        }).execute()
        
        return {"result": f"C'est fait Ilyas ! Réservé pour {args.get('size')} personnes à {formatted_time}."}

    except Exception as e:
        print(f"❌ ERREUR : {str(e)}")
        return {"result": "Erreur technique, mais j'ai bien noté vos infos."}