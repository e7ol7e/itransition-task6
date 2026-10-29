-- Nominal v1. All generation entry points are real PostgreSQL procedures.
create schema if not exists nominal;
create table nominal.locales(locale text primary key, label text not null, country text not null);
insert into nominal.locales values ('en_US','English · United States','US'),('de_DE','Deutsch · Deutschland','DE');
create table nominal.names(locale text references nominal.locales, kind text, ordinal integer, value text not null, primary key(locale,kind,ordinal));
create table nominal.terms(locale text references nominal.locales, kind text, ordinal integer, value text not null, primary key(locale,kind,ordinal));
create table nominal.cities(locale text references nominal.locales, ordinal integer, city text, region text, postal_low integer, postal_high integer, area text, phone_block text, primary key(locale,ordinal));
create table nominal.markov_transitions(locale text references nominal.locales, context text, letter text, frequency bigint, cumulative bigint, total bigint, primary key(locale,context,letter));
create table nominal.assets(locale text primary key references nominal.locales, version text not null default '1', dictionary jsonb not null, model jsonb not null);

create procedure nominal.uniform(p_locale text, p_seed text, p_position bigint, p_stream text, out value double precision)
language plpgsql as $$
begin
  -- JSON array encoding prevents ambiguous concatenation; 52 bits are exact in float8.
  value := ((('x' || substr(md5(jsonb_build_array(p_locale,p_seed,p_position,p_stream)::text),1,13))::bit(52)::bigint)::double precision + 0.5) / 4503599627370496.0;
end $$;

create procedure nominal.integer(p_locale text, p_seed text, p_position bigint, p_stream text, p_min integer, p_max integer, out value integer)
language plpgsql as $$
declare u double precision;
begin
  if p_min > p_max then raise exception 'Minimum exceeds maximum'; end if;
  call nominal.uniform(p_locale,p_seed,p_position,p_stream,u);
  value := (p_min::bigint + floor(u * (p_max::bigint-p_min+1))::bigint)::integer;
end $$;

create procedure nominal.normal(p_locale text, p_seed text, p_position bigint, p_stream text, p_mean double precision, p_sd double precision, out value double precision)
language plpgsql as $$
declare u double precision; v double precision;
begin
  if p_sd < 0 then raise exception 'Standard deviation must be nonnegative'; end if;
  call nominal.uniform(p_locale,p_seed,p_position,p_stream||'/u',u);
  call nominal.uniform(p_locale,p_seed,p_position,p_stream||'/v',v);
  value := p_mean + p_sd * sqrt(-2*ln(u))*cos(2*pi()*v);
end $$;

create procedure nominal.choose(p_dictionary jsonb, p_locale text, p_seed text, p_position bigint, p_category text, p_stream text, out value text)
language plpgsql as $$
declare i integer; items jsonb;
begin
  items := p_dictionary -> p_category;
  if items is null or jsonb_array_length(items)=0 then raise exception 'Missing dictionary category: %',p_category; end if;
  call nominal.integer(p_locale,p_seed,p_position,p_stream,0,jsonb_array_length(items)-1,i);
  value := items ->> i;
end $$;

create procedure nominal.rebuild_locale(p_locale text)
language plpgsql as $$
declare d jsonb; m jsonb; c jsonb;
begin
  if not exists(select 1 from nominal.locales where locale=p_locale) then raise exception 'Unknown locale'; end if;
  delete from nominal.markov_transitions where locale=p_locale;
  insert into nominal.markov_transitions
  with words as (select '^^'||lower(value)||'$' as word from nominal.terms where locale=p_locale and kind='corpus'),
  counts as (select substr(word,i,2) context,substr(word,i+2,1) letter,count(*) frequency from words cross join lateral generate_series(1,length(word)-2) i group by 1,2)
  select p_locale,context,letter,frequency,sum(frequency) over(partition by context order by letter collate "C"),sum(frequency) over(partition by context) from counts;
  select jsonb_object_agg(category,items) into d from (
    select kind category,jsonb_agg(value order by ordinal) items from nominal.names where locale=p_locale group by kind
    union all select kind,jsonb_agg(value order by ordinal) from nominal.terms where locale=p_locale group by kind
  ) x;
  select jsonb_agg(to_jsonb(x) order by ordinal) into c from (select * from nominal.cities where locale=p_locale) x;
  d := d || jsonb_build_object('cities',c);
  select jsonb_object_agg(context,choices) into m from (
    select context,jsonb_agg(jsonb_build_array(letter,cumulative,total) order by letter collate "C") choices
    from nominal.markov_transitions where locale=p_locale group by context
  ) x;
  insert into nominal.assets(locale,dictionary,model) values(p_locale,d,m)
  on conflict(locale) do update set dictionary=excluded.dictionary,model=excluded.model;
end $$;

create procedure nominal.word(p_dictionary jsonb,p_model jsonb,p_locale text,p_seed text,p_position bigint,out value text)
language plpgsql as $$
declare context text; choice jsonb; u double precision; target double precision; letter text; attempt integer; step integer;
begin
  for attempt in 1..4 loop
    value := ''; context := '^^';
    for step in 1..18 loop
      call nominal.uniform(p_locale,p_seed,p_position,'word/'||attempt||'/'||step,u);
      letter := null;
      for choice in select * from jsonb_array_elements(p_model->context) loop
        target := u*(choice->>2)::bigint;
        if target < (choice->>1)::bigint then letter:=choice->>0; exit; end if;
      end loop;
      exit when letter is null or letter='$';
      value := value||letter; context:=right(context||letter,2);
    end loop;
    if length(value) between 4 and 14 then value:=initcap(value); return; end if;
  end loop;
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,'corpus','word/fallback',value);
end $$;

create procedure nominal.full_name(p_dictionary jsonb,p_locale text,p_seed text,p_position bigint,out value jsonb)
language plpgsql as $$
declare gender integer; variant integer; first_name text; last_name text; middle_name text; formatted text; category text;
begin
  call nominal.integer(p_locale,p_seed,p_position,'name/gender',0,1,gender);
  category:=case when gender=0 then 'male' else 'female' end;
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,category,'name/first',first_name);
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,'last','name/last',last_name);
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,category,'name/middle',middle_name);
  call nominal.integer(p_locale,p_seed,p_position,'name/variant',0,7,variant);
  formatted:=first_name||' '||last_name;
  if variant in (1,2) then formatted:=first_name||' '||middle_name||' '||last_name;
  elsif variant=3 then formatted:=first_name||' '||left(middle_name,1)||'. '||last_name;
  elsif variant=4 then formatted:='Dr. '||formatted;
  elsif variant=5 then formatted:=case when p_locale='de_DE' then case when gender=0 then 'Herr ' else 'Frau ' end else case when gender=0 then 'Mr. ' else 'Ms. ' end end||formatted;
  elsif variant=6 and p_locale='en_US' then formatted:=formatted||' Jr.';
  end if;
  value:=jsonb_build_object('first',first_name,'last',last_name,'full',formatted);
end $$;

create procedure nominal.address(p_dictionary jsonb,p_model jsonb,p_locale text,p_seed text,p_position bigint,out value jsonb)
language plpgsql as $$
declare city jsonb; i integer; house integer; postal integer; apt integer; variant integer; root text; suffix text; street text; line text; formatted text;
begin
  call nominal.integer(p_locale,p_seed,p_position,'address/city',0,jsonb_array_length(p_dictionary->'cities')-1,i);
  city:=p_dictionary->'cities'->i;
  call nominal.integer(p_locale,p_seed,p_position,'address/house',1,case when p_locale='en_US' then 9999 else 250 end,house);
  call nominal.integer(p_locale,p_seed,p_position,'address/postal',(city->>'postal_low')::integer,(city->>'postal_high')::integer,postal);
  call nominal.integer(p_locale,p_seed,p_position,'address/variant',0,3,variant);
  call nominal.integer(p_locale,p_seed,p_position,'address/unit',1,99,apt);
  call nominal.word(p_dictionary,p_model,p_locale,p_seed,p_position,root);
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,'suffix','address/suffix',suffix);
  street:=root||case when p_locale='en_US' then ' ' else '' end||suffix;
  if p_locale='en_US' then
    line:=house||' '||street||case when variant=0 then ', Apt '||apt when variant=1 then ', Suite '||apt else '' end;
    formatted:=line||', '||(city->>'city')||', '||(city->>'region')||' '||lpad(postal::text,5,'0');
  else
    line:=street||' '||house||case when variant=0 then ', Wohnung '||apt when variant=1 then 'a' else '' end;
    formatted:=line||', '||lpad(postal::text,5,'0')||' '||(city->>'city');
  end if;
  value:=jsonb_build_object('full',formatted,'street',line,'city',city->>'city','region',city->>'region','postal_code',lpad(postal::text,5,'0'),'area',city->>'area','phone_block',city->>'phone_block');
end $$;

create procedure nominal.coordinates(p_locale text,p_seed text,p_position bigint,out value jsonb)
language plpgsql as $$
declare u double precision; v double precision;
begin
  call nominal.uniform(p_locale,p_seed,p_position,'geo/z',u);
  call nominal.uniform(p_locale,p_seed,p_position,'geo/longitude',v);
  value:=jsonb_build_object('latitude',degrees(asin(2*u-1)),'longitude',360*v-180);
end $$;

create procedure nominal.physical(p_dictionary jsonb,p_locale text,p_seed text,p_position bigint,out value jsonb)
language plpgsql as $$
declare height double precision; weight double precision; eyes text; attempt integer;
begin
  for attempt in 1..100 loop
    call nominal.normal(p_locale,p_seed,p_position,'physical/height/'||attempt,172,9,height);
    exit when height between 110 and 230;
  end loop;
  if height not between 110 and 230 then raise exception 'Height rejection limit exceeded'; end if;
  for attempt in 1..100 loop
    call nominal.normal(p_locale,p_seed,p_position,'physical/weight/'||attempt,75,12,weight);
    exit when weight between 35 and 180;
  end loop;
  if weight not between 35 and 180 then raise exception 'Weight rejection limit exceeded'; end if;
  call nominal.choose(p_dictionary,p_locale,p_seed,p_position,'eyes','physical/eyes',eyes);
  value:=jsonb_build_object('height_cm',round(height::numeric,1),'weight_kg',round(weight::numeric,1),'eye_color',eyes);
end $$;

create procedure nominal.phone(p_address jsonb,p_locale text,p_seed text,p_position bigint,out value text)
language plpgsql as $$
declare n integer; variant integer; area text; block text; ending text;
begin
  area:=p_address->>'area'; block:=p_address->>'phone_block';
  call nominal.integer(p_locale,p_seed,p_position,'phone/variant',0,2,variant);
  call nominal.integer(p_locale,p_seed,p_position,'phone/ending',0,case when p_locale='en_US' then 99 else 999 end,n);
  if p_locale='en_US' then
    ending:=lpad((100+n)::text,4,'0');
    value:=case variant when 0 then '('||area||') 555-'||ending when 1 then '+1 '||area||'-555-'||ending else area||'.555.'||ending end;
  else
    ending:=lpad(n::text,3,'0');
    value:=case variant when 0 then '0'||area||' / '||block||ending when 1 then '+49 '||area||' '||block||' '||ending else '(0'||area||') '||block||ending end;
  end if;
end $$;

create procedure nominal.email(p_name jsonb,p_locale text,p_seed text,p_position bigint,out value text)
language plpgsql as $$
declare local_part text; namespace text;
begin
  local_part:=lower((p_name->>'first')||'.'||(p_name->>'last'));
  local_part:=replace(replace(replace(replace(local_part,'ä','ae'),'ö','oe'),'ü','ue'),'ß','ss');
  local_part:=regexp_replace(local_part,'[^a-z0-9.]','','g');
  namespace:=substr(md5(jsonb_build_array(p_locale,p_seed)::text),1,8);
  value:=left(local_part,35)||'.'||namespace||'.'||p_position||'@example.com';
end $$;

create procedure nominal.contact(p_dictionary jsonb,p_model jsonb,p_locale text,p_seed text,p_position bigint,out value jsonb)
language plpgsql as $$
declare n jsonb; a jsonb; g jsonb; p jsonb; phone text; email text;
begin
  call nominal.full_name(p_dictionary,p_locale,p_seed,p_position,n);
  call nominal.address(p_dictionary,p_model,p_locale,p_seed,p_position,a);
  call nominal.coordinates(p_locale,p_seed,p_position,g);
  call nominal.physical(p_dictionary,p_locale,p_seed,p_position,p);
  call nominal.phone(a,p_locale,p_seed,p_position,phone);
  call nominal.email(n,p_locale,p_seed,p_position,email);
  value:=jsonb_build_object('position',p_position,'locale',p_locale,'name',n,'address',a-'area'-'phone_block','coordinates',g,'physical',p,'phone',phone,'email',email);
end $$;

create procedure nominal.batch(p_locale text,p_seed text,p_batch bigint,p_size integer,out result jsonb)
language plpgsql as $$
declare d jsonb; m jsonb; item jsonb; items jsonb:='[]'; i integer;
begin
  if p_locale is null or p_seed is null or length(p_seed)>64 or p_batch is null or p_batch<0 or p_batch>100000000 or p_size is null or p_size not between 1 and 100 then raise exception 'Invalid request'; end if;
  select dictionary,model into d,m from nominal.assets where locale=p_locale;
  if d is null then raise exception 'Unsupported locale'; end if;
  for i in 0..p_size-1 loop
    call nominal.contact(d,m,p_locale,p_seed,p_batch*p_size+i,item);
    items:=items||jsonb_build_array(item);
  end loop;
  result:=jsonb_build_object('version','1','locale',p_locale,'seed',p_seed,'batch',p_batch,'size',p_size,'start',p_batch*p_size,'contacts',items);
end $$;

-- Admin-only benchmark. Materializes every contact, hashing ALL fields.
create procedure nominal.benchmark(p_locale text,p_seed text,p_count integer,out result jsonb)
language plpgsql as $$
declare d jsonb; m jsonb; item jsonb; started timestamptz; elapsed double precision; checksum text:=''; i integer;
begin
  if p_count not between 1 and 1000000 then raise exception 'Count must be 1..1000000'; end if;
  select dictionary,model into d,m from nominal.assets where locale=p_locale;
  if d is null then raise exception 'Unsupported locale'; end if;
  started:=clock_timestamp();
  for i in 0..p_count-1 loop
    call nominal.contact(d,m,p_locale,p_seed,i,item);
    checksum:=md5(checksum||item::text);
  end loop;
  elapsed:=extract(epoch from clock_timestamp()-started);
  result:=jsonb_build_object('locale',p_locale,'count',p_count,'seconds',elapsed,'users_per_second',p_count/elapsed,'checksum',checksum,'server',version(),'finished_at',clock_timestamp());
end $$;
