import {useState, useEffect} from "react";
import Login from "../components/Login";

const AuthPage = ({initialMethod }) => {
    const [method, setMethod] = useState(initialMethod);

    useEffect(()=> {
        setMethod(initialMethod);
    }, [initialMethod]);

    const route = method === 'login' ? '/api/token/' : '/api/user/register/';
    
    return(
        <div>
            <Login route = {route} method = {method}/> 
        </div>
    )       
}

export default AuthPage;