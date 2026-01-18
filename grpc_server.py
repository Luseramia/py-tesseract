import grpc
from concurrent import futures
import time
import numpy as np
import cv2
import ocr_pb2
import ocr_pb2_grpc
from main import extract_info_from_image
import requests
import json
from datetime import datetime
import os

class OCRService(ocr_pb2_grpc.OCRServiceServicer):
    def ProcessImage(self, request, context):
        try:
            # Convert bytes to numpy array for cv2
            nparr = np.frombuffer(request.image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details('Invalid image data')
                return ocr_pb2.OCRResult()

            # Process image
            result = extract_info_from_image(img)

            # Get extra fields
            username = request.username if request.username else "default_user"
            type_of_expense = request.type_of_expense if request.type_of_expense else "General"

            # Call n8n
            webhook_response = create_expenses(
                username=username,
                type_of_expense=type_of_expense,
                amount=result['amount'],
                date=result['date'],
                expense_description=result['ref'],
                note=result['raw_text']
            )
            
            return ocr_pb2.OCRResult(
                amount=str(result.get("amount", "")),
                date=str(result.get("date", "")),
                ref=str(result.get("ref", "")),
                raw_text=str(result.get("raw_text", "")),
                error="",
                webhook_result=json.dumps(webhook_response)
            )
        except Exception as e:
            print(f"Error processing image: {e}")
            return ocr_pb2.OCRResult(error=str(e))

    def ProcessBatch(self, request, context):
        response = ocr_pb2.BatchOCRResult()
        for img_req in request.requests:
            try:
                nparr = np.frombuffer(img_req.image_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if img is None:
                    response.results.append(ocr_pb2.OCRResult(error="Invalid image data"))
                    continue

                result = extract_info_from_image(img)

                username = img_req.username if img_req.username else "default_user"
                type_of_expense = img_req.type_of_expense if img_req.type_of_expense else "General"

                webhook_response = create_expenses(
                        username=username,
                        type_of_expense=type_of_expense,
                        amount=result['amount'],
                        date=result['date'],
                        expense_description=result['ref'],
                        note=result['raw_text']
                    )

                response.results.append(ocr_pb2.OCRResult(
                    amount=str(result.get("amount", "")),
                    date=str(result.get("date", "")),
                    ref=str(result.get("ref", "")),
                    raw_text=str(result.get("raw_text", "")),
                    error="",
                    webhook_result=json.dumps(webhook_response)
                ))
                
            except Exception as e:
                response.results.append(ocr_pb2.OCRResult(error=str(e)))
        
        return response
    
def create_expenses(username, type_of_expense, amount, date, expense_description, note):
        production_api = os.environ.get('N8N_PRODUCTION_API', "http://n8n.n8n.svc.cluster.local:443/webhook/d3b132c4-8380-4b0d-96a6-ea11d2f040a9")
        
        headers = {
            "Content-Type": "application/json",
            "x-AUTH": "MTI5OTk0OTgxOTE0MTU1NDE5Nw",
        }
        
        payload = {
            "username": username,
            "typeOfExpense": 'BY MOBILE APP',
            "amount": amount,
            "date": date,
            "expenseDiscription": expense_description,
            "note": note
        }
        
        try:
            response = requests.post(production_api, headers=headers, json=payload)
            print("Status:", response.status_code)
            print("Headers:", response.headers)
            
            try:
                return response.json()
            except ValueError:
                return {"error": "Not JSON", "raw": response.text}
                
        except Exception as err:
            print("Fetch error:", err)
            return {"error": str(err)}
    
    
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ocr_pb2_grpc.add_OCRServiceServicer_to_server(OCRService(), server)
    server.add_insecure_port('[::]:50051')
    print("gRPC Server starting on port 50051...")
    server.start()
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == '__main__':
    serve()
