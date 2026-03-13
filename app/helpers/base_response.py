

def base_response(status_code=200, success=False, message=None, data=None):
    response_data = {
        "success": success,
        "message": message,
        "data": data if data is not None else {},
        "status_code": status_code
    }

    return response_data
