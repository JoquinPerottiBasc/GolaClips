// Firebase Web SDK config for GolaClips
// Get these values from: Firebase Console → Project Settings → General → Your apps → Web
// If no web app exists yet, click "Add app" and choose Web (</>)

const firebaseConfig = {
  apiKey: "PEGAR_AQUI_TU_API_KEY",
  authDomain: "PEGAR_AQUI_TU_PROJECT_ID.firebaseapp.com",
  projectId: "PEGAR_AQUI_TU_PROJECT_ID",
  storageBucket: "PEGAR_AQUI_TU_PROJECT_ID.appspot.com",
  messagingSenderId: "PEGAR_AQUI_TU_MESSAGING_SENDER_ID",
  appId: "PEGAR_AQUI_TU_APP_ID",
};

firebase.initializeApp(firebaseConfig);
