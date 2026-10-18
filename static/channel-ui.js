/* Shared onboarding and channel colors for both dashboards. */
window.ChannelUI = (() => {
  const palettes = {
    forest: ['#101a16','#192720','#213229','#3b5142','#e9f1e7','#a9bbaa','#c7e5ac'],
    midnight: ['#101829','#19243b','#22314b','#3a5075','#edf2fc','#a9bad7','#a8ccff'],
    plum: ['#211529','#2e2038','#3c2a48','#60416e','#f6edf9','#c8b0d3','#deb8f2'],
    ember: ['#241813','#33251e','#443027','#70503d','#fff0e4','#d3b7a3','#f0be8e'],
    crimson: ['#220f14','#331722','#452029','#70404c','#fdeef1','#d3a9b3','#f2a8bc']
  };
  function apply(channel) {
    const colors = palettes[channel?.ui_palette] || palettes[channel?.id === 'wolfie-blues' ? 'midnight' : 'forest'];
    ['bg','panel','panel2','line','text','muted','accent'].forEach((key,i)=>document.documentElement.style.setProperty('--'+key,colors[i]));
    document.documentElement.style.setProperty('--ink', colors[4]);
    document.documentElement.style.setProperty('--ink-soft', colors[5]);
    document.documentElement.style.setProperty('--accent-dark', colors[6]);
    document.documentElement.dataset.channelPalette = channel?.ui_palette || 'forest';
  }
  function onboard(done) {
    const dialog = document.createElement('dialog');
    dialog.className = 'channel-onboarding';
    dialog.innerHTML = `<h2>Add channel</h2><p>Separate media, Google credentials, and workspace colors.</p>
      <form><div class="channel-fields">
      <label>Channel name<input name="name" required maxlength="80" placeholder="Wolfie Blues"></label>
      <label>Channel ID<input name="id" required pattern="[a-z0-9_-]{1,64}"></label>
      <label>Google OAuth client ID<input name="oauth_client_id" required autocomplete="off"></label>
      <label>Google OAuth client secret<input type="password" name="oauth_client_secret" required autocomplete="new-password"></label>
      <label>Music folder<input name="music_dir" required></label>
      <label>Background folder<input name="background_dir" required></label>
      <label>Thumbnail folder<input name="thumbnail_dir" required></label>
      <label>Watermark PNG file or folder<input name="watermark_path" required></label>
      <label>Output subfolder<input name="output_dir" required></label>
      <label>Workspace colors<select name="ui_palette"><option value="midnight">Midnight blue</option><option value="forest">Forest green</option><option value="plum">Plum</option><option value="ember">Warm amber</option></select></label>
      </div><p>Folders are created on save. Add your media, then connect YouTube. Final videos are also exported to your output subfolder; job records stay in jobs/.</p>
      <p>Google redirect URI: <code>http://localhost:5001/callback</code> (or the configured server callback).</p>
      <p role="alert" class="channel-error"></p><button type="button" data-cancel>Cancel</button> <button class="primary" type="submit">Create channel</button></form>`;
    document.body.append(dialog);
    const form = dialog.querySelector('form');
    const edited = new Set();
    form.addEventListener('input', event => {
      const name = event.target.name;
      edited.add(name);
      if (!['name','id'].includes(name)) return;
      if (name === 'name' && !edited.has('id')) form.elements.id.value = form.elements.name.value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,64);
      const slug = form.elements.id.value.replace(/-blues$/, '') || 'channel';
      const defaults = {music_dir:`music-${slug}`,background_dir:`backgroundImages-${slug}`,thumbnail_dir:`thumbnail-${slug}`,watermark_path:`watermark-${slug}`,output_dir:`jobs/output-${slug}`};
      Object.entries(defaults).forEach(([key,value])=>{if(!edited.has(key)) form.elements[key].value=value;});
    });
    dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>dialog.remove());
    form.onsubmit = async event => {
      event.preventDefault();
      const button=form.querySelector('[type=submit]');button.disabled=true;
      try {
        const data = Object.fromEntries(new FormData(form));
        const response=await fetch('/api/studio/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,profile_id:'blues',create_only:true})});
        const result=await response.json();
        if(!response.ok) throw new Error(result.error || 'Could not create channel');
        form.elements.oauth_client_secret.value='';dialog.close();await done(result);
      } catch(error) {dialog.querySelector('.channel-error').textContent=error.message;button.disabled=false;}
    };
    dialog.showModal();
  }
  return {apply,onboard};
})();
