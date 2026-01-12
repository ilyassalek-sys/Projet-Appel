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
    return {"status": "online", "message": "Serveur de Luigi opérationnel"}

# --- ROUTE 1 : INITIALISATION DE L'APPEL ---
@app.post("/call/init")
async def init_call(request: Request):
    payload = await request.json()
    
    # On récupère le numéro appelé
    called_number = payload.get('message', {}).get('phone_number', {}).get('number') or '+12406509923'
    
    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    if not response.data:
        return {"assistant": {"firstMessage": "Désolé, je ne trouve pas ce restaurant."}}
    
    resto = response.data[0]

    system_instruction = f"""
    Tu es l'assistant vocal de {resto['name']}.
    
    CONSIGNES RÉSERVATION :
    1. Demande : Nom, Nombre de personnes, et Date/Heure (ex: ce soir à 20h).
    2. Si tu n'as pas le numéro de téléphone, demande-le.
    3. Une fois les infos obtenues, appelle 'book_table'.
    
    IMPORTANT : Si l'outil dit que le client a déjà 2 réservations, informe-le poliment du refus.
    """

    return {
        "assistant": {
            "firstMessage": f"Bienvenue chez {resto['name']} ! Pour combien de personnes souhaitez-vous réserver ?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "systemPrompt": system_instruction
            }
        }
    }

# --- ROUTE 2 : LOGIQUE DE RÉSERVATION ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    payload = await request.json()
    print(f"DEBUG Payload reçu: {payload}")

    # Extraction hybride (Compatible API Request Vapi)
    args = payload.get('arguments') or payload
    if 'message' in payload and not args.get('name'):
        tool_call = payload.get('message', {}).get('toolCalls', [{}])[0]
        args = tool_call.get('function', {}).get('arguments', {})

    # 1. Gestion du Numéro de téléphone
    customer_phone = (
        payload.get('customer', {}).get('number') or 
        payload.get('message', {}).get('call', {}).get('customer', {}).get('number') or
        args.get('phone_backup')
    )
    
    if not customer_phone or "anonymous" in str(customer_phone).lower():
        return {"result": "Il me manque votre numéro de téléphone pour valider."}

    # 2. Formatage de la Date
    time_input = args.get('time_str')
    parsed_date = dateparser.parse(time_input, settings={'PREFER_DATES_FROM': 'future', 'DATE_ORDER': 'DMY'})
    
    if not parsed_date:
        return {"result": "Je n'ai pas compris la date. Pouvez-vous répéter le jour et l'heure ?"}
    
    formatted_time = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
    today_date = parsed_date.strftime("%Y-%m-%d")

    # 3. Récupération du Restaurant ID
    called_number = payload.get('phone_number', {}).get('number') or '+12406509923'
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    if not resto_resp.data:
        return {"result": "Erreur : Restaurant introuvable."}
    restaurant_id = resto_resp.data[0]['id']

    # 4. VÉRIFICATION ANTI-SPAM (Max 2)
    existing_res = db.table('reservations') \
        .select("id", count="exact") \
        .eq('customer_phone', customer_phone) \
        .eq('restaurant_id', restaurant_id) \
        .ilike('reservation_time', f"{today_date}%") \
        .execute()

    if existing_res.count and existing_res.count >= 2:
        return {"result": f"Désolé, vous avez déjà atteint la limite de 2 réservations pour aujourd'hui."}

    # 5. INSERTION DANS SUPABASE
    try:
        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_phone": str(customer_phone),
            "customer_name": args.get('name'),
            "party_size": int(args.get('size')),
            "reservation_time": formatted_time,
            "status": "confirmed"
        }).execute()
        
        return {"result": f"C'est parfait ! Votre table pour {args.get('size')} au nom de {args.get('name')} est réservée pour le {formatted_time}."}
    except Exception as e:
        print(f"Erreur Supabase: {e}")
        return {"result": "Désolé, j'ai eu une erreur technique lors de l'enregistrement."}