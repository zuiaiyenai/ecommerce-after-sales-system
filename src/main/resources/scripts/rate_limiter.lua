local current = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])

if current == 1 or ttl < 0 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end

if current <= tonumber(ARGV[1]) then
    return 1
end

return 0
