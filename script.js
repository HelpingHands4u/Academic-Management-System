document.querySelectorAll("[data-demo-login]").forEach(form=>{
  form.addEventListener("submit",e=>{
    e.preventDefault();
    const email=form.querySelector("input[type=\"email\"], input[data-credential=\"email\"]").value.trim();
    const password=form.querySelector("input[type=\"password\"]").value;
    const role=form.getAttribute("data-role");
    const credentials={
      student:{email:"DeveloperS.student@srh.me",password:"086",target:"student-dashboard.html"},
      faculty:{email:"DeveloperS.faculty@srh.me",password:"086",target:"faculty-dashboard.html"}
    };
    const valid=credentials[role] && email===credentials[role].email && password===credentials[role].password;
    const message=form.querySelector(".login-error");
    if(!valid){
      message.textContent="Wrong credentials. Please check your university email and password.";
      message.classList.add("show");
      return;
    }
    message.classList.remove("show");
    window.location.href=credentials[role].target;
  });
});

// Home-page background video: adding the video file automatically activates playback.
const hero=document.querySelector(".hero");
const heroVideo=document.querySelector(".hero-video");
if(hero && heroVideo){
  const activate=()=>{
    if(heroVideo.currentSrc || heroVideo.querySelector("source")?.getAttribute("src")){
      hero.classList.add("has-video");
      heroVideo.play().catch(()=>{});
    }
  };
  heroVideo.addEventListener("loadeddata",activate);
  activate();
}
