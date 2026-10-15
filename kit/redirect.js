// The site root forwards to the kit, keeping ?dev=1, ?deck= and ?new=1.
location.replace("app/" + location.search + location.hash);
