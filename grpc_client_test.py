import grpc
import ocr_pb2
import ocr_pb2_grpc
import sys

def run():
    print("Connecting to gRPC server...")
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = ocr_pb2_grpc.OCRServiceStub(channel)
        
        image_path = r"c:\Users\tarch\OneDrive\เดสก์ท็อป\qr\1765679961630.jpg"
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except FileNotFoundError:
            print(f"Test image not found at {image_path}")
            return

        print("\n--- Testing Single Image Process ---")
        response = stub.ProcessImage(ocr_pb2.ImageRequest(image_data=image_bytes, filename="test.jpg"))
        print(f"Result:")
        print(f"  Amount: {response.amount}")
        print(f"  Date: {response.date}")
        print(f"  Ref: {response.ref}")
        if response.error:
            print(f"  Error: {response.error}")

        print("\n--- Testing Batch Process (2 images) ---")
        batch_req = ocr_pb2.BatchImageRequest()
        batch_req.requests.append(ocr_pb2.ImageRequest(image_data=image_bytes, filename="img1.jpg"))
        batch_req.requests.append(ocr_pb2.ImageRequest(image_data=image_bytes, filename="img2.jpg"))
        
        batch_resp = stub.ProcessBatch(batch_req)
        for i, res in enumerate(batch_resp.results):
            print(f"Image {i+1}:")
            print(f"  Amount: {res.amount}")
            print(f"  Date: {res.date}")
            print(f"  Ref: {res.ref}")
            if res.error:
                print(f"  Error: {res.error}")

if __name__ == '__main__':
    run()
